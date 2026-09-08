import unittest
from PySide6.QtTest import QTest
from app import MainWindow
import test_download_navigation as navigation

class ThumbnailResizeTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def settle(self):
        for _ in range(8):self.app.processEvents();QTest.qWait(2)

    def test_divider_resizes_icons_and_restores_height(self):
        for i in range(25):self.image(10,f'{i:02}.png')
        window=self.window();window.show();self.settle()
        window.thumb_list.setCurrentRow(2);window.image_view.actual_size();window.image_view.scale(2,2)
        selected=window.current_path;transform=window.image_view.transform()
        old_height=window.thumb_list.iconSize().height()
        total=sum(window.center_splitter.sizes())
        window.center_splitter.moveSplitter(total-300,1);self.settle()
        self.assertGreater(window.thumb_list.iconSize().height(),old_height)
        self.assertEqual(window.current_path,selected)
        self.assertEqual(window.image_view.transform(),transform)
        self.assertFalse(window.thumb_list.isWrapping())
        state=window._build_state();saved=state['thumbnail_panel_height']
        self.assertGreater(saved,250)
        reopened=MainWindow(self.root,state);self.addCleanup(reopened.close);reopened.show();self.settle()
        self.assertAlmostEqual(reopened.center_splitter.sizes()[1],saved,delta=3)
        big=window.thumb_list.iconSize().height()
        window.center_splitter.moveSplitter(total-120,1);self.settle()
        self.assertLess(window.thumb_list.iconSize().height(),big)
        self.assertEqual(window.current_path,selected)

if __name__=='__main__':unittest.main()