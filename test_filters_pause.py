import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from PySide6.QtTest import QTest
from app import MainWindow
from image_annotations import AnnotationDocument,empty_state
from image_filters import is_color,is_edited
import test_download_navigation as navigation

class FilterPauseTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def wait_filters(self,window):
        for _ in range(400):
            self.app.processEvents()
            if not window._filter_jobs:return
            QTest.qWait(5)
        self.fail('Image filter did not finish')

    def mark(self,path):
        document=AnnotationDocument(path)
        state=empty_state();state['contrast']=1.3
        document.commit(state);document.save()
        return document

    def test_color_detects_rgb_monochrome_and_real_color(self):
        gray=self.image(1,'gray.png');Image.new('RGB',(50,50),(90,90,90)).save(gray)
        color=self.image(1,'color.png')
        self.assertFalse(is_color(gray));self.assertTrue(is_color(color))
        pal=self.image(1,'palette.png')
        Image.new('RGB',(50,50),'green').convert('P').save(pal)
        self.assertTrue(is_color(pal))

    def test_edited_includes_adjustments_and_history_but_not_pen_settings(self):
        path=self.image(1,'test.png');document=AnnotationDocument(path);document.save()
        self.assertFalse(is_edited(path))
        document.pen['color']='#ff00ff';document.save()
        self.assertFalse(is_edited(path))
        document=self.mark(path);self.assertTrue(is_edited(path))
        document.step();document.save()
        self.assertTrue(is_edited(path))

    def test_mission_filter_finds_edits_across_sols_and_combines_color(self):
        first=self.image(1,'edited_color.png');self.mark(first)
        gray=self.image(2,'edited_gray.png');Image.new('RGB',(50,50),'gray').save(gray);self.mark(gray)
        self.image(2,'untouched.png')
        window=self.window()
        window.filter_edited.setChecked(True)
        window.filter_scope.setCurrentIndex(1)
        self.wait_filters(window)
        self.assertEqual(set(window.current_images),{first,gray})
        window.filter_color.setChecked(True);self.wait_filters(window)
        self.assertEqual(window.current_images,[first])
        self.assertEqual(window.current_sol,1)
        self.assertEqual(window.current_path,first)
        self.assertEqual(window.sol_list.currentItem().data(256)[0],1)

    def test_filter_preserves_selected_image_and_zoom_if_it_matches(self):
        self.image(1,'first.png');path=self.image(1,'second.png')
        window=self.window();window.thumb_list.setCurrentRow(1)
        window.image_view.scale(2,2);before=window.image_view.transform()
        window.filter_color.setChecked(True);self.wait_filters(window)
        self.assertEqual(window.current_path,path)
        self.assertEqual(window.image_view.transform(),before)
        window.filter_edited.setChecked(True);self.wait_filters(window)
        self.assertIsNone(window.current_path)
        self.assertEqual(window.thumb_list.count(),0)
        window.filter_edited.setChecked(False);self.wait_filters(window)
        self.assertEqual(window.thumb_list.count(),2)

    def test_sol_switch_clears_thumbnails_before_slow_scan_finishes(self):
        first=self.image(1,'first.png');self.image(2,'second.png')
        window=self.window();window.show();self.app.processEvents()
        self.assertEqual(window.thumb_list.count(),1)
        started=threading.Event();release=threading.Event()
        from catalog import list_images
        def slow(folder,cancel=None):
            started.set();release.wait(2)
            return list_images(folder,cancel)
        with patch('image_filters.list_images',side_effect=slow):
            window.sol_list.setCurrentRow(1)
            self.assertTrue(started.wait(1))
            self.assertEqual(window.thumb_list.count(),0)
            self.assertEqual(window._thumb_queue,[])
            self.assertTrue(window.thumbnail_loading.isVisible())
            self.assertEqual(window.thumbnail_loading_progress.maximum(),0)
            self.assertIn('SOL1',window.thumbnail_loading_label.text())
            token=window._filter_token
            window._image_filter_progress(token,300)
            self.assertIn('300',window.thumbnail_loading_label.text())
            window._image_filter_done(token-1,[])
            self.assertTrue(window.thumbnail_loading.isVisible())
            release.set();self.wait_filters(window)
        self.assertEqual(window.current_path,first)
        self.assertEqual(window.thumb_list.count(),1)
        window._load_thumb_batch()
        self.assertFalse(window.thumbnail_loading.isVisible())

    def test_filtered_empty_result_replaces_busy_indicator(self):
        self.image(1,'a.png');window=self.window();window.show();self.app.processEvents()
        window.filter_edited.setChecked(True)
        self.assertEqual(window.thumb_list.count(),0)
        self.wait_filters(window)
        self.assertTrue(window.thumbnail_loading.isVisible())
        self.assertEqual(window.thumbnail_loading_progress.maximum(),1)
        self.assertIn('Nenhuma imagem',window.thumbnail_loading_label.text())

    def test_cancelled_filter_cannot_replace_new_mission_results(self):
        self.image(1,'old.png');window=self.window()
        window.filter_color.setChecked(True)
        stale=window._filter_token
        window.missions.library_root=str(self.root/'Library')
        window._choose_source('perseverance')
        self.wait_filters(window)
        window._image_filter_done(stale,[(1,self.root/'SOL1',self.root/'SOL1'/'old.png')])
        self.assertIsNone(window.current_path)

    def test_other_sol_download_does_not_refresh_folder_filter(self):
        self.image(10,'working.png')
        window=self.window()
        window.filter_color.setChecked(True);self.wait_filters(window)
        selected=window.thumb_list.currentItem()
        window.image_view.scale(2,2)
        transform=window.image_view.transform()
        with patch.object(window._filter_timer,'start') as schedule, \
             patch.object(window.thumb_list,'doItemsLayout') as layout:
            for i in range(3):
                path=self.image(9,f'download{i}.png')
                window._on_download_file_downloaded(9,str(path))
            schedule.assert_not_called();layout.assert_not_called()
        self.assertIs(window.thumb_list.currentItem(),selected)
        self.assertEqual(window.image_view.transform(),transform)
        path=self.image(10,'new.png')
        with patch.object(window._filter_timer,'start') as schedule:
            window._on_download_file_downloaded(10,str(path))
            schedule.assert_called_once_with(500)
        window._request_image_filter(background=True);self.wait_filters(window)
        self.assertIn(path,window.current_images)
        self.assertIs(window.thumb_list.currentItem(),selected)

    def test_background_filter_without_new_images_does_not_relayout(self):
        self.image(10,'working.png');window=self.window()
        window.filter_color.setChecked(True);self.wait_filters(window)
        count=window.filter_count.text()
        with patch.object(window.thumb_list,'doItemsLayout') as layout, \
             patch.object(window.filter_count,'setText') as label:
            window._request_image_filter(background=True)
            self.wait_filters(window)
            layout.assert_not_called();label.assert_not_called()
        self.assertEqual(window.filter_count.text(),count)

    def test_stop_becomes_continue_and_keeps_requested_start_mode(self):
        self.image(10,'test.png');window=self.window()
        thread=Mock();thread.isRunning.return_value=True
        worker=Mock();window._download_thread=thread;window._download_worker=worker
        window._download_mode='from_sol';window._download_requested_start_sol=1;window._download_resume_sol=7
        window._toggle_download_pause()
        worker.stop.assert_called_once();thread.requestInterruption.assert_called_once()
        self.assertTrue(window._download_paused)
        self.assertFalse(window.download_stop_button.isEnabled())
        thread.isRunning.return_value=False
        window._on_downloader_finished('Atualização interrompida.')
        window._on_download_thread_finished()
        self.assertEqual(window.download_stop_button.text(),'Continuar')
        self.assertTrue(window.download_stop_button.isEnabled())
        window._state=window._build_state()
        with patch.object(window,'_launch_downloader') as launch:
            window._toggle_download_pause()
        launch.assert_called_once_with(start_sol=7)

    def test_paused_session_reopens_without_starting_download(self):
        self.image(10,'test.png');window=self.window()
        window._download_paused=True;window._download_resume_sol=10
        window.missions.profiles['curiosity']['auto_download']=True
        state=window._build_state(pending_resume=False)
        with patch('app.QTimer.singleShot') as timer:
            reopened=MainWindow(self.root,state)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.download_stop_button.text(),'Continuar')
        self.assertTrue(reopened.download_stop_button.isEnabled())
        self.assertFalse(any(call.args[0]==700 for call in timer.call_args_list))

    def test_resume_selected_archive_uses_original_observation(self):
        self.image(1,'test.png');window=self.window()
        window.missions.library_root=str(self.root/'Library');window._choose_source('marte_mars_reconnaissance_orbiter')
        window._download_paused=True
        window._state['download']={'paused':True,'mode':'only_sol','resume_sol':123,'pending_resume':False}
        with patch.object(window,'_launch_downloader') as launch:window._resume_saved_download()
        launch.assert_called_once_with(only_sol=123)

if __name__=='__main__':unittest.main()
