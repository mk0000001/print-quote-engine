from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_FLOOR, localcontext

D = Decimal


def _d(value, name, minimum=D('0')):
    if isinstance(value,(bool,float)) or len(str(value))>60:
        raise ValueError(f'INVALID_DECIMAL:{name}')
    try:
        result = D(str(value))
    except Exception as exc:
        raise ValueError(f'INVALID_DECIMAL:{name}') from exc
    if not result.is_finite() or result < minimum or result>D('1000000000000'):
        raise ValueError(f'INVALID_DECIMAL:{name}')
    return result

def _integer(value,name,minimum=0):
    result=_d(value,name,D(minimum))
    if result!=result.to_integral_value(): raise ValueError(f'INVALID_INTEGER:{name}')
    return int(result)


def _truth(value):
    return value is True or str(value).lower() == 'true'


def _ceil(value, unit):
    return (value / unit).to_integral_value(rounding=ROUND_CEILING) * unit


def _plain(value):
    value = value.normalize() if value else D('0')
    return format(value, 'f')


def _size_rule(material, dimensions, policy):
    mapping = policy['size_rate_policy_map'].get(material)
    if not mapping:
        return None
    key = mapping['policy_key']
    rules = policy['low_temp_size_rate_rules'] if key == 'LOW_TEMP_SIZE_RATE' else policy['chamber_size_rate_rules']
    for rule in sorted(rules, key=lambda item: int(item['rank'])):
        maximums = [rule.get('max_x_mm'), rule.get('max_y_mm'), rule.get('max_z_mm')]
        if all(limit is None or dim <= D(limit) for dim, limit in zip(dimensions, maximums)):
            return rule
    return None


def _long_risk(printer, seconds, basis, policy):
    if printer == 'A1':
        profile = policy['long_print_risk_profiles']['A1_LONG_RISK_V2']
        if seconds > int(D(profile['trigger_after_hours']) * 3600):
            return basis * D(profile['risk_rate']) * D(profile['loss_fraction_assumption']), _truth(profile['activates_floor']), profile['risk_rate']
        return D('0'), False, '0'
    if printer == 'Q2':
        profile = policy['long_print_risk_profiles']['Q2_LONG_RISK_V1']
        hours = D(seconds) / 3600
        for tier in profile['tiers']:
            lower = tier.get('min_hours_exclusive')
            upper = tier.get('max_hours')
            if (lower is None or hours > D(lower)) and (upper is None or hours <= D(upper)):
                return basis * D(tier['risk_rate']), _truth(tier['activates_floor']), tier['risk_rate']
    return D('0'), False, '0'


def calculate(data: dict, policy: dict) -> dict:
    with localcontext() as ctx:
        ctx.prec=50
        ctx.rounding=ROUND_HALF_EVEN
        return _calculate(data,policy)

def _calculate(data: dict, policy: dict) -> dict:
    reasons, warnings, components = [], [], []
    printer = str(data.get('printer', '')).upper()
    material = str(data.get('material', '')).upper()
    if printer not in policy['printer_catalog']:
        reasons.append('UNKNOWN_PRINTER')
    elif not policy['printer_catalog'][printer]['enabled']:
        warnings.append('PRINTER_NOT_PRODUCTION_ELIGIBLE_ADMIN_QUOTE_ONLY')
    rate_key = policy['material_rate_key_map'].get(material)
    if not rate_key or rate_key not in policy['base_hourly_rates']:
        reasons.append('UNKNOWN_OR_UNSUPPORTED_MATERIAL')
        base_rate = D('0')
    else:
        base_rate = D(policy['base_hourly_rates'][rate_key])
    seconds = _integer(data.get('duration_seconds'),'duration_seconds')
    _integer(data.get('part_count',1),'part_count',1)
    billable = max(seconds, int(policy['machine_billing']['minimum_billable_seconds']))
    dimensions = [_d(v, f'dimensions_mm[{i}]', D('0.000001')) for i, v in enumerate(data.get('dimensions_mm') or [])]
    if len(dimensions) != 3:
        raise ValueError('DIMENSIONS_REQUIRE_XYZ')
    size = _size_rule(material, dimensions, policy)
    if size is None:
        reasons.append('SIZE_POLICY_UNRESOLVED')
        multiplier = D('1')
    else:
        multiplier = D(size['hourly_rate_multiplier'])
    machine = base_rate * multiplier * D(billable) / 3600
    components.append(('MACHINE', '장비 시간', machine))

    grams = _d(data.get('grams'), 'grams')
    market = data.get('material_price') or {}
    package = _d(market.get('package_price'), 'package_price')
    weight = _d(market.get('package_weight_g'), 'package_weight_g', D('0.000001'))
    if _truth(market.get('tax_included')):
        package /= D('1') + _d(market.get('tax_rate'), 'source_tax_rate')
    material_amount = grams * package / weight * D(policy['material_pricing']['markup_multiplier'])
    components.append(('MATERIAL', '필라멘트', material_amount))

    if data.get('energy_kwh') in (None, ''):
        power_key=f'{printer}_ABS_ASA' if material in ('ABS','ASA') else f'{printer}_GENERAL'
        power = policy['resolved_power_w'].get(power_key) or policy['resolved_power_w'].get(f'{printer}_GENERAL')
        if power:
            energy_kwh = D(power) * D(seconds) / D('3600000')
            warnings.append('ENERGY_ESTIMATED_FROM_PRIVATE_POWER_PROFILE')
        else:
            energy_kwh = D('0')
            reasons.append('ENERGY_INPUT_REQUIRED')
    else:
        energy_kwh = _d(data['energy_kwh'], 'energy_kwh')
    energy = energy_kwh * D(policy['energy']['unit_rate'])
    components.append(('ENERGY', '전력', energy))

    base_reference = machine + material_amount + energy
    surcharges = []
    colors = _integer(data.get('colors',1),'colors',1)
    if colors>1 and printer=='Q1': reasons.append('Q1_MULTICOLOR_NOT_SUPPORTED')
    if colors>1 and material in ('TPU','TPE'): reasons.append('FLEXIBLE_MULTICOLOR_NOT_SUPPORTED')
    if material in ('PA6-CF','PPS-CF') and printer!='Q1': reasons.append('ENGINEERING_REQUIRES_Q1_POOL')
    color_rule = next((r for r in policy['normal_multicolor_rules'] if int(r['min_colors']) <= colors <= int(r['max_colors'])), None)
    if not color_rule:
        reasons.append('MULTICOLOR_TIER_REQUIRES_MANUAL_REVIEW')
    elif colors > 1:
        color_amount = D(policy['base_hourly_rates']['PLA_STANDARD']) * D(color_rule['surcharge_rate']) * D(billable) / 3600
        surcharges.append(('NORMAL_MULTICOLOR', '일반 멀티컬러', color_amount, _truth(color_rule['activates_floor'])))
    full_spectrum = _truth(data.get('full_spectrum'))
    fs_changes=_integer(data.get('fs_changes',0),'fs_changes')
    if not full_spectrum and fs_changes:
        raise ValueError('FS_COUNT_WITHOUT_FS_MODE')
    if full_spectrum and colors > 1:
        reasons.append('MULTICOLOR_FULL_SPECTRUM_INTERACTION_UNRESOLVED')
    if full_spectrum:
        profile = policy['full_spectrum_profiles']['H2C_FULL_SPECTRUM_V2']
        if printer != 'H2C':
            reasons.append('FULL_SPECTRUM_PROFILE_NOT_AVAILABLE_FOR_PRINTER')
        fs_amount = D(fs_changes) * D(profile['per_event_rate'])
        surcharges.append(('FULL_SPECTRUM', 'Full Spectrum', fs_amount, _truth(profile['activates_floor'])))
    long_amount, long_floor, long_rate = _long_risk(printer, seconds, base_reference, policy)
    if long_amount:
        surcharges.append(('LONG_RISK', '장시간 출력 위험', long_amount, long_floor))
    risk=data.get('support_risk') or {}
    tier=str(risk.get('tier','LOW')).upper()
    risk_rates=policy.get('support_risk_surcharge_rates',{})
    if tier in ('MEDIUM','HIGH') and tier not in risk_rates:reasons.append('SUPPORT_RISK_POLICY_UNCONFIGURED')
    if tier in risk_rates and D(str(risk_rates[tier]))>0:
        risk_amount=machine*D(str(risk_rates[tier]))
        surcharges.append(('SUPPORT_RISK','서포트 전도 위험',risk_amount,False))
        warnings.append('SUPPORT_RISK_SURCHARGE_APPLIED')
    components.extend((code, label, value) for code, label, value, _ in surcharges)
    surcharge_sum = sum((row[2] for row in surcharges), D('0'))
    floor_activated = any(row[3] and row[2] > 0 for row in surcharges)
    floor_amount = base_reference * D(policy['conditional_floor']['rate']) if floor_activated else D('0')
    conditional = max(surcharge_sum, floor_amount)
    if floor_amount > surcharge_sum:
        components.append(('CONDITIONAL_FLOOR_ADJUSTMENT', '조건부 최소 할증 보정', floor_amount-surcharge_sum))

    extras = data.get('extras') or {}
    fixed = policy['fixed_fees']
    if _truth(extras.get('plate_setup')):
        components.append(('PLATE_STANDARDIZATION', '플레이트 세팅', D(fixed['PLATE_STANDARDIZATION']['amount_krw'])))
    if _truth(extras.get('nozzle_change')):
        components.append(('NOZZLE_CHANGE', '노즐 교체', D(fixed['NOZZLE_CHANGE']['amount_krw'])))
    if _truth(extras.get('small_nozzle')):
        components.append(('SMALL_NOZZLE_RISK', '0.2 노즐 위험', D(fixed['SMALL_NOZZLE_RISK']['amount_krw'])))
        if '-CF' in material or '-GF' in material:
            reasons.append('CF_GF_SMALL_NOZZLE_REQUIRES_MANUAL_REVIEW')
    extra_spools = _integer(extras.get('extra_spools',0),'extra_spools')
    if extra_spools:
        components.append(('EXTRA_SPOOL_HANDLING', '추가 스풀 교체', D(extra_spools) * D(fixed['EXTRA_SPOOL_HANDLING']['amount_krw'])))
    plate_purchase = _d(extras.get('plate_purchase') or '0', 'plate_purchase')
    if plate_purchase:
        components.append(('PLATE_PROCUREMENT', '신규 플레이트 부담', plate_purchase * D(policy['plate_procurement']['customer_share_ratio'])))
    if _integer(extras.get('extra_drying_seconds',0),'extra_drying_seconds') > 0:
        reasons.append('EXTRA_DRYING_PRICE_NOT_CONFIGURED')
    if _truth(extras.get('rush')):
        components.append(('RUSH_ANALYSIS', '48시간 분석 Rush', D(policy['rush']['fee_krw'])))

    raw = machine + material_amount + energy + conditional + sum((v for c, _, v in components if c in {'PLATE_STANDARDIZATION','NOZZLE_CHANGE','SMALL_NOZZLE_RISK','EXTRA_SPOOL_HANDLING','PLATE_PROCUREMENT','RUSH_ANALYSIS'}), D('0'))
    unit = D(policy['rounding']['final_service_supply']['unit_krw'])
    subtotal = _ceil(raw, unit)
    shipping = _d(data.get('shipping') or '0', 'shipping')
    shipping_taxable=data.get('shipping_taxable')
    if shipping and _truth(data.get('tax_applicable')) and shipping_taxable is None:
        reasons.append('SHIPPING_TAX_CLASSIFICATION_REQUIRED')
    tax_base=subtotal+(shipping if shipping_taxable is True else D('0'))
    tax_rate=_d(data.get('output_tax_rate') or '0','output_tax_rate')
    if tax_rate>D('1'): raise ValueError('INVALID_OUTPUT_TAX_RATE')
    vat = tax_base*tax_rate if _truth(data.get('tax_applicable')) else D('0')
    tax_rule=policy.get('tax',{}).get('amount_rounding',{})
    tax_unit=D(tax_rule.get('unit_krw','1'))
    mode=tax_rule.get('mode','CEILING')
    rounding={'CEILING':ROUND_CEILING,'HALF_UP':ROUND_HALF_UP,'FLOOR':ROUND_FLOOR}.get(mode)
    if not rounding or tax_unit<=0: raise ValueError('INVALID_TAX_ROUNDING_POLICY')
    vat=(vat/tax_unit).to_integral_value(rounding=rounding)*tax_unit
    discount_percent=_d(data.get('discount_percent','0'),'discount_percent')
    if discount_percent>D('100'):raise ValueError('INVALID_DISCOUNT_PERCENT')
    discount_reason=data.get('discount_reason','')
    if not isinstance(discount_reason,str) or len(discount_reason)>500 or any(ord(c)<32 and c not in '\n\r\t' for c in discount_reason):
        raise ValueError('INVALID_DISCOUNT_REASON')
    discount_reason=discount_reason.strip()
    if discount_percent and not discount_reason:raise ValueError('DISCOUNT_REASON_REQUIRED')
    before_subtotal,before_vat,before_shipping=subtotal,vat,shipping
    if discount_percent:
        factor=D('1')-discount_percent/D('100')
        subtotal=(subtotal*factor).quantize(D('1'),rounding=ROUND_HALF_UP)
        shipping=(shipping*factor).quantize(D('1'),rounding=ROUND_HALF_UP)
        tax_base=subtotal+(shipping if shipping_taxable is True else D('0'))
        vat=tax_base*tax_rate if _truth(data.get('tax_applicable')) else D('0')
        vat=(vat/tax_unit).to_integral_value(rounding=rounding)*tax_unit
    discount={'percent':_plain(discount_percent),'reason':discount_reason,
              'before_subtotal':_plain(before_subtotal),'before_vat':_plain(before_vat),'before_shipping':_plain(before_shipping),
              'before_total':_plain(before_subtotal+before_vat+before_shipping),
              'service_amount':_plain(before_subtotal-subtotal),'shipping_amount':_plain(before_shipping-shipping),
              'tax_reduction':_plain(before_vat-vat),
              'amount':_plain(before_subtotal+before_vat+before_shipping-subtotal-vat-shipping),
              'basis':'SERVICE_AND_SHIPPING_WITH_RECALCULATED_TAX','rounding':'KRW_HALF_UP_THEN_POLICY_VAT_ROUNDING'}
    result_components = [{'code': c, 'label': label, 'amount': _plain(value)} for c, label, value in components]
    return {'currency': 'KRW', 'policy_revision': policy['policy_revision'], 'billable_seconds': billable,
            'components': result_components, 'raw_service_supply': _plain(raw), 'subtotal': _plain(subtotal),
            'vat': _plain(vat), 'shipping': _plain(shipping), 'grand_total': _plain(subtotal + vat + shipping),
            'discount':discount,
            'warnings': warnings, 'manual_review_reasons': sorted(set(reasons)),
            'trace': {'math_context': 'DECIMAL_P50_HALF_EVEN_V1','calculator_version':policy['calculator_version'],'source_sha256':policy['source_sha256'], 'size_rule': size['code'] if size else None,
                      'size_multiplier': _plain(multiplier), 'long_risk_rate': str(long_rate),
                      'conditional_floor': {'activated': floor_activated, 'policy_sum': _plain(surcharge_sum),
                                            'floor_amount': _plain(floor_amount), 'selected': _plain(conditional)},
                      'rounding_unit': _plain(unit)}}
