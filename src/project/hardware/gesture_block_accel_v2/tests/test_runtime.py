"""Check the real split ONNX paths with an independent NumPy block callback."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from blocks16_runtime import SplitBlocksNetwork,make_fpga_classifier
from export_blocks import reference,compare

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(2)
        cls.params=[dict(np.load(ROOT/f'export/params/block{b}.npz',allow_pickle=False)) for b in (0,1)]
    def test_full_logits_four_inputs(self):
        calls=[]
        def compute(x):
            self.assertEqual(x.shape,(1,40,28,28));self.assertEqual(x.dtype,np.float32)
            self.assertTrue(x.flags.c_contiguous);calls.append(1)
            return reference(x,self.params)
        network=SplitBlocksNetwork(compute)
        for name in ('black','gradient','seeded_noise','real_frame'):
            with self.subTest(name=name):
                folder=ROOT/'export/cases'/name
                blob=np.load(folder/'model_input.npy',allow_pickle=False);before=blob.copy()
                actual=network.forward(blob)
                compare(actual,np.load(folder/'model_logits.npy',allow_pickle=False).reshape(-1))
                np.testing.assert_array_equal(blob,before)
                self.assertIsNotNone(network.last_timing)
        self.assertEqual(len(calls),4)
    def test_bad_hardware_output_fails_before_suffix(self):
        blob=np.load(ROOT/'export/cases/gradient/model_input.npy',allow_pickle=False)
        for result in (np.zeros((40,28,28),np.float32),np.zeros((1,40,28,28),np.float64),np.full((1,40,28,28),np.nan,np.float32)):
            network=SplitBlocksNetwork(lambda x:result)
            with self.assertRaisesRegex(RuntimeError,'two-block output'):network.forward(blob)
            self.assertIsNone(network.last_timing)
    def test_factory_uses_hardware_and_counts_only_successful_logits(self):
        params=self.params
        class Accelerator:
            def __init__(self,path,parameters):
                assert path.name=='gesture_blocks56.bit'
                assert len(parameters)==2 and parameters[0].size==20712
                self.fail=False;self.closed=False;self.last_timing={'total_ms':1.}
            def run(self,x):
                if self.fail:raise RuntimeError('hardware failure')
                return reference(x,params)
            def close(self):self.closed=True
        with patch('blocks16_runtime.runpy.run_path',return_value={}),patch('blocks16_driver.BlocksAccelerator',Accelerator):
            classifier,accel=make_fpga_classifier()
        folder=ROOT/'export/cases/real_frame';blob=np.load(folder/'model_input.npy',allow_pickle=False)
        compare(classifier.logits(blob),np.load(folder/'model_logits.npy',allow_pickle=False).reshape(-1))
        self.assertEqual(classifier.fpga_completed_frames,1)
        self.assertEqual(classifier.last_fpga_timing,{'total_ms':1.})
        accel.fail=True
        with self.assertRaisesRegex(RuntimeError,'hardware failure'):classifier.logits(blob)
        self.assertEqual(classifier.fpga_completed_frames,1)
        self.assertIsNone(classifier.last_split_timing);self.assertIsNone(classifier.last_fpga_timing)
        classifier.close();self.assertTrue(accel.closed)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    (ROOT/'reports/runtime_host_tests.json').write_text(json.dumps({'passed':result.wasSuccessful(),'tests':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'board_tested':False,
        'scope':'Real prefix/suffix OpenCV inference, independent NumPy target blocks, four complete logits vectors and invalid-output rejection'},indent=2)+'\n')
    sys.exit(not result.wasSuccessful())
