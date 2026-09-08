import copy
import json
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

    def test_cancelled_filter_cannot_replace_new_mission_results(self):
        self.image(1,'old.png');window=self.window()
        window.filter_color.setChecked(True)
        stale=window._filter_token
        window.missions.library_root=str(self.root/'Library')
        window._choose_source('perseverance')
        self.wait_filters(window)
        window._image_filter_done(stale,[(1,self.root/'SOL1',self.root/'SOL1'/'old.png')])
        self.assertIsNone(window.current_path)

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