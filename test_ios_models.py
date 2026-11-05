import unittest
import ios_models

class IOSModelTests(unittest.TestCase):
    def test_reference_visible_without_runtime(self):
        p=ios_models.references([],[])[0]
        self.assertEqual(len(p['displays']),2)
        self.assertFalse(p['available'])
        with self.assertRaisesRegex(ValueError,'未发现官方'):
            ios_models.resolve({'id':'iphone-duo'},[p])

    def test_renamed_iphone_does_not_match(self):
        p=ios_models.references([{'name':'iPhone Duo','identifier':'official-duo'}],[{'platform':'iOS','id':'fake','device_type':'iphone17','name':'iPhone Duo'}])[0]
        self.assertFalse(p['available'])

    def test_only_matching_simulator_can_be_selected(self):
        p=ios_models.references([{'name':'iPhone Duo','identifier':'official-duo'}],[{'platform':'iOS','id':'real','device_type':'official-duo','name':'iPhone Duo · iOS 27'}])[0]
        self.assertTrue(p['available'])
        self.assertEqual(ios_models.resolve({'id':'iphone-duo','device':'real'},[p])[1]['id'],'real')
        with self.assertRaises(ValueError):ios_models.resolve({'id':'iphone-duo','device':'other'},[p])
