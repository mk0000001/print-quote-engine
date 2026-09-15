import unittest
from print_quote_engine.energy import estimate_energy


class ThermalEnergyTests(unittest.TestCase):
    def fixture(self):
        geometry={'bed_mm':[250,250],'height_mm':250,'enclosed':True,'active_chamber':False,'source':'SYNTHETIC'}
        policy={'energy_model':{'version':'THERMAL_V1','geometries':{'A':geometry,'B':{**geometry,'bed_mm':[350,350]}}},
                'energy_telemetry':{'profiles':{'A':[{'mean_w':200,'bed_c':60,'nozzle_c':220,'sample_hours':10}]}}}
        data={'printer':'A','material':'PLA','duration_seconds':3600,'grams':'50','process_settings':{'bed_temp':'60','nozzle_temp':'220'}}
        return data,policy

    def test_reference_and_larger_bed_extrapolation(self):
        data,policy=self.fixture();result=estimate_energy(data,policy)
        self.assertEqual(result['method'],'HA_PRINT_HISTORY');self.assertEqual(result['average_w'],200)
        bigger=estimate_energy({**data,'printer':'B'},policy)
        self.assertGreater(bigger['average_w'],200);self.assertEqual(bigger['method'],'THERMAL_ESTIMATE_CALIBRATED')
        self.assertFalse(bigger['is_job_measurement'])

    def test_snapshot_determinism_zero_time_and_no_telemetry(self):
        data,policy=self.fixture()
        self.assertEqual(estimate_energy(data,policy),estimate_energy(data,policy))
        self.assertEqual(float(estimate_energy({**data,'duration_seconds':0},policy)['kwh']),0)
        policy.pop('energy_telemetry')
        result=estimate_energy(data,policy)
        self.assertGreater(float(result['kwh']),0);self.assertEqual(result['method'],'THERMAL_ESTIMATE')

    def test_missing_policy_retains_legacy_path(self):
        self.assertIsNone(estimate_energy({},{}))


if __name__=='__main__':unittest.main()
