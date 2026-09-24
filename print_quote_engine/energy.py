"""Transparent thermal estimates, optionally calibrated by independent telemetry.

Coefficients below are engineering assumptions, not manufacturer ratings or a
validated electrical simulation. No HA connection or device identifiers belong here.
"""
import math
from decimal import Decimal, InvalidOperation


def job_quantity(value,name,integer=False):
    """Use the calculator's quantity range; never substitute zero for invalid input."""
    if isinstance(value,(bool,float)) or len(str(value))>60:raise ValueError('INVALID_DECIMAL:'+name)
    try:result=Decimal(str(value))
    except (InvalidOperation,ValueError) as exc:raise ValueError('INVALID_DECIMAL:'+name) from exc
    if not result.is_finite() or not 0<=result<=Decimal('1000000000000'):
        raise ValueError('INVALID_DECIMAL:'+name)
    if integer and result!=result.to_integral_value():raise ValueError('INVALID_INTEGER:'+name)
    return result


def finite(value,default,low=0,high=100000):
    try:
        value=float(value)
        return value if math.isfinite(value) and low<=value<=high else default
    except (TypeError,ValueError):return default


def conditions(data):
    settings=data.get('process_settings') or {};material=str(data.get('material','PLA')).upper()
    defaults={'PLA':(60,220,25),'PETG':(80,245,25),'ABS':(100,250,50),'ASA':(100,255,50),
              'TPU':(50,225,25),'TPE':(50,225,25),'PA6-CF':(100,290,55),'PPS-CF':(120,330,65)}
    bed,nozzle,chamber=defaults.get(material,(80,250,25));assumptions=[]
    result={}
    for key,field,default,maximum in [('bed_c','bed_temp',bed,150),('nozzle_c','nozzle_temp',nozzle,450),('chamber_c','chamber_temp',chamber,120)]:
        value=finite(settings.get(field),None,0,maximum)
        if value is None:value=default;assumptions.append(field+'_MATERIAL_DEFAULT')
        result[key]=value
    result['ambient_c']=finite(settings.get('ambient_temp'),25,0,50)
    result['heated_hotends']=finite(settings.get('heated_hotends'),1,1,12)
    if settings.get('heated_hotends') is None:assumptions.append('ONE_ACTIVE_HOTEND_STANDBY_HEAT_UNKNOWN')
    return result,assumptions


def thermal_w(geometry,temps,coefficients=None):
    coefficients=coefficients or {}
    width,depth=[finite(x,250,50,2000)/1000 for x in geometry.get('bed_mm',[250,250])]
    height=finite(geometry.get('height_mm'),250,50,2000)/1000
    ambient=temps.get('ambient_c',25);area=width*depth
    bed_delta=max(0,temps['bed_c']-ambient);nozzle_delta=max(0,temps['nozzle_c']-ambient)
    # Effective bed heat loss includes convection/radiation; chamber only if actively heated.
    bed=area*finite(coefficients.get('bed_loss_w_m2_k'),12,0,100)*bed_delta
    hotend=finite(coefficients.get('hotend_loss_w_k'),.12,0,10)*nozzle_delta*temps.get('heated_hotends',1)
    chamber=(2*(width*depth+width*height+depth*height)*finite(coefficients.get('chamber_loss_w_m2_k'),3.5,0,100)*max(0,temps['chamber_c']-ambient)
             if geometry.get('active_chamber') else 0)
    return {'electronics_motors_w':finite(coefficients.get('electronics_motors_w'),35,0,1000),'bed_loss_w':bed,'hotend_loss_w':hotend,'chamber_loss_w':chamber}


def estimate_energy(data,policy):
    model=policy.get('energy_model')
    if not model:return None  # Preserve old immutable policy snapshots.
    printer=str(data['printer']).upper();geometries=model.get('geometries',{})
    geometry=geometries.get(printer,{'bed_mm':[250,250],'height_mm':250,'source':'ASSUMED_250_MM'})
    temps,assumptions=conditions(data)
    if geometry.get('assumed'):assumptions.append(geometry['assumed'])
    coefficients=model.get('coefficients',{})
    parts=thermal_w(geometry,temps,coefficients);raw=sum(parts.values());watts=raw;method='THERMAL_ESTIMATE';reference=None
    candidates=[]
    for key,profiles in policy.get('energy_telemetry',{}).get('profiles',{}).items():
        for p in profiles:
            if key not in geometries or not all(finite(p.get(k),None,0,500) is not None for k in ('bed_c','nozzle_c')):continue
            ref_temps={'bed_c':p['bed_c'],'nozzle_c':p['nozzle_c'],'chamber_c':p.get('chamber_c') or 25,'ambient_c':25,'heated_hotends':1}
            reference_raw=sum(thermal_w(geometries[key],ref_temps,coefficients).values())
            if reference_raw<=0:continue
            calibration=finite(p.get('mean_w'),None,40,10000)
            if calibration is None:continue
            scale=calibration/reference_raw
            if not .25<=scale<=4:continue
            distance=abs(temps['bed_c']-ref_temps['bed_c'])/10+abs(temps['nozzle_c']-ref_temps['nozzle_c'])/30
            if geometry.get('active_chamber') or geometries[key].get('active_chamber'):distance+=abs(temps['chamber_c']-ref_temps['chamber_c'])/10
            if key!=printer:distance+=20
            if bool(geometry.get('enclosed'))!=bool(geometries[key].get('enclosed')):distance+=10
            candidates.append((distance,-p.get('sample_hours',0),key,p,scale,ref_temps))
    if candidates:
        _,_,key,p,scale,ref_temps=min(candidates,key=lambda r:r[:2])
        close=(key==printer and abs(temps['bed_c']-ref_temps['bed_c'])<=5 and abs(temps['nozzle_c']-ref_temps['nozzle_c'])<=15
               and (not geometry.get('active_chamber') or abs(temps['chamber_c']-ref_temps['chamber_c'])<=5)
               and temps['heated_hotends']==1)
        watts=p['mean_w'] if close else raw*scale
        method='HA_PRINT_HISTORY' if close else 'THERMAL_ESTIMATE_CALIBRATED'
        reference={'printer':key,**p,'scale':scale}
        if key!=printer:assumptions.append('OTHER_MACHINE_THERMAL_SCALING')
        if not close:assumptions.append('TEMPERATURE_GEOMETRY_EXTRAPOLATION_NOT_MEASURED')
    seconds=job_quantity(data.get('duration_seconds'),'duration_seconds',integer=True)
    grams=job_quantity(data.get('grams'),'grams')
    # Only add polymer sensible heating to uncalibrated estimates. Measured averages already include it.
    polymer_wh=(float(grams)*1.8*max(0,temps['nozzle_c']-temps['ambient_c'])/3600 if reference is None else 0)
    width,depth=geometry.get('bed_mm',[250,250])
    # One cold start, 3 mm aluminium equivalent bed, 80% warm-up efficiency.
    warmup_wh=(float(width)*float(depth)/1e6*.003*2700*900*max(0,temps['bed_c']-temps['ambient_c'])/3600/.8)
    assumptions.extend(['BED_BUILD_VOLUME_PROXY_NOT_PHYSICAL_HEATER_AREA','COLD_START_3MM_ALUMINIUM_EQUIVALENT_80_PERCENT',
                        'HEAT_LOSS_COEFFICIENTS_ASSUMED','NO_DIRECT_JOB_ENERGY_METER'])
    if policy.get('energy_telemetry',{}).get('sync_stale'):assumptions.append('HA_SYNC_STALE_USING_CACHED_HISTORY')
    kwh=(Decimal(str(watts))*Decimal(str(seconds))/Decimal(3600000)+Decimal(str(warmup_wh+polymer_wh))/1000) if seconds else Decimal(0)
    return {'method':method,'kwh':str(kwh),'average_w':watts,'warmup_wh':warmup_wh if seconds else 0,
            'polymer_heat_wh':polymer_wh if seconds else 0,'conditions':temps,'geometry':geometry,'reference':reference,
            'telemetry_collected_at_ts':policy.get('energy_telemetry',{}).get('collected_at_ts'),
            'condition_sources':(data.get('process_settings') or {}).get('energy_condition_sources',{}),
            'thermal_components_w':parts,'model_version':model.get('version'),'assumptions':assumptions,
            'confidence':'REFERENCE' if method=='HA_PRINT_HISTORY' else 'LOW','is_job_measurement':False}
