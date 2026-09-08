import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import MainWindow
from config import load_app_state

class SessionRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'images';self.root.mkdir()
        for target,value in [('config._state_file_candidates',[Path(self.temp.name)/'session.json']),('config._legacy_state_candidates',[])]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch('app.QTimer.singleShot');p.start();self.addCleanup(p.stop)
    def make_images(self,sol,count):
        folder=self.root/f'SOL{sol}';folder.mkdir(exist_ok=True)
        for i in range(count):Image.new('RGB',(40,30),'red').save(folder/f'{i:02}.png')
    def settle(self):
        for _ in range(25):self.app.processEvents();QTest.qWait(10)
    def test_disk_close_reopen_returns_to_saved_sol_image_and_visible_thumbnail(self):
        self.make_images(10,40)
        w=MainWindow(self.root,{'source':'curiosity'});w.show();self.settle()
        w.thumb_list.setCurrentRow(35);selected=w.current_path;w.close()
        self.make_images(100,1)
        saved=load_app_state();self.assertEqual(saved['selected_sol'],10)
        reopened=MainWindow(self.root,saved);self.addCleanup(reopened.close);reopened.show();self.settle()
        self.assertEqual(reopened.current_sol,10);self.assertEqual(reopened.current_path,selected)
        self.assertEqual(reopened.thumb_list.currentRow(),35)
        rect=reopened.thumb_list.visualItemRect(reopened.thumb_list.currentItem())
        self.assertTrue(reopened.thumb_list.viewport().rect().intersects(rect))
    def test_empty_filter_keeps_last_worked_image_for_next_launch(self):
        self.make_images(10,3)
        w=MainWindow(self.root,{'source':'curiosity'});w.thumb_list.setCurrentRow(2);selected=w.current_path
        w._image_filter_done(w._filter_token,[])
        self.assertIsNone(w.current_path);w.close()
        reopened=MainWindow(self.root,load_app_state());self.addCleanup(reopened.close)
        self.assertEqual(reopened.current_path,selected)

if __name__=='__main__':unittest.main()