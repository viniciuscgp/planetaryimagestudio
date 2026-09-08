import unittest
from PIL import Image
from PySide6.QtTest import QTest
from unittest.mock import patch
import test_download_navigation as navigation

class ThumbnailScrollTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def settle(self):
        for _ in range(10):
            self.app.processEvents();QTest.qWait(1)

    def test_activity_and_icon_updates_preserve_scroll_and_view(self):
        for i in range(40):self.image(10,f'{i:02}.png')
        window=self.window();window.show();self.settle()
        window.thumb_list.setCurrentRow(2);window.image_view.scale(2,2)
        self.settle();bar=window.thumb_list.horizontalScrollBar();bar.setValue(1800)
        position=bar.value();width=window.thumb_list.width();selected=window.thumb_list.currentItem()
        image=window.current_path;transform=window.image_view.transform()
        for i in range(3):
            window._on_download_file_started(20,'LONG_FILENAME_'*30+'.jpg',i+1,100)
            window._on_download_message('Baixando '+str(i))
            window._on_download_file_progress(20,'file.jpg',i*20,1024,2048)
            path=self.image(10,f'new_{i}.png');window._on_download_file_downloaded(10,str(path))
            self.settle()
            self.assertEqual(bar.value(),position)
            self.assertEqual(window.thumb_list.width(),width)
            self.assertIs(window.thumb_list.currentItem(),selected)
            self.assertEqual(window.current_path,image)
            self.assertEqual(window.image_view.transform(),transform)
        # User navigation must still be able to reveal another thumbnail.
        window.thumb_list.setCurrentRow(42);window.thumb_list.scrollToItem(window.thumb_list.currentItem());self.settle()
        self.assertNotEqual(bar.value(),position)

    def test_background_filter_appends_without_reselection_or_scroll(self):
        paths=[self.image(10,f'{i:02}.png') for i in range(40)]
        window=self.window();window.show();self.settle()
        bar=window.thumb_list.horizontalScrollBar();bar.setValue(1800)
        position=bar.value();selected=window.thumb_list.currentItem()
        path=self.image(10,'new.png');rows=[(10,p.parent,p) for p in paths+[path]]
        window._filter_background=True
        with patch.object(window,'_thumb_changed',wraps=window._thumb_changed) as selection:
            window._image_filter_done(window._filter_token,rows)
            self.settle()
            selection.assert_not_called()
        self.assertIs(window.thumb_list.currentItem(),selected)
        self.assertEqual(bar.value(),position)
        self.assertEqual(window.thumb_list.count(),41)
        # Repeated results must not duplicate images or move the user's new scroll position.
        bar.setValue(2200);window._image_filter_done(window._filter_token,rows);self.settle()
        self.assertEqual(bar.value(),2200)
        self.assertEqual(window.thumb_list.count(),41)

if __name__=='__main__':unittest.main()