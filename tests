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

    def test_case_normalization_preserves_geometry_material_and_telemetry(self):
        data,policy=self.fixture()
        data={**data,'material':'ABS','process_settings':{}}
        expected=estimate_energy(data,policy)
        for printer,material in [('a','ABS'),('A','abs'),('a','abs')]:
            with self.subTest(printer=printer,material=material):
                self.assertEqual(estimate_energy({**data,'printer':printer,'material':material},policy),expected)

    def test_long_prints_do_not_turn_into_zero_energy(self):
        data,policy=self.fixture()
        for seconds in (100000,100001,128266,604800):
            with self.subTest(seconds=seconds):
                result=estimate_energy({**data,'duration_seconds':seconds},policy)
                expected=200*seconds/3600000+result['warmup_wh']/1000
                self.assertAlmostEqual(float(result['kwh']),expected,places=10)
                self.assertGreater(result['warmup_wh'],0)

    def test_large_valid_mass_is_not_discarded(self):
        data,policy=self.fixture();policy.pop('energy_telemetry')
        result=estimate_energy({**data,'grams':'100001'},policy)
        self.assertGreater(result['polymer_heat_wh'],9000)

    def test_invalid_job_quantities_fail_instead_of_defaulting_to_zero(self):
        data,policy=self.fixture()
        for field,value in [('duration_seconds',-1),('duration_seconds','NaN'),('duration_seconds','1.5'),('grams','Infinity'),('grams',None)]:
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):estimate_energy({**data,field:value},policy)


if __name__=='__main__':unittest.main()
