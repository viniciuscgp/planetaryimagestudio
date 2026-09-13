import unittest
from unittest.mock import patch
from planetary_studio.annotations.image_annotations import AnnotationDocument
import tests.test_download_navigation as navigation


class InlineAdjustmentTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_live_adjustment_preserves_zoom_and_saves_before_navigation(self):
        first = self.image(10, 'a.png')
        second = self.image(10, 'b.png')
        window = self.window()
        window.image_view.actual_size()
        window.image_view.scale(2, 2)
        transform = window.image_view.transform()
        window._inline_controls['brightness'][0].setValue(150)
        window._flush_inline_adjustments()
        self.assertEqual(window.brightness, 150)
        self.assertEqual(window.image_view.transform(), transform)
        self.assertEqual(AnnotationDocument(first).state['brightness'], 150)
        window._inline_controls['brightness'][0].setValue(170)
        window.thumb_list.setCurrentRow(1)
        self.assertEqual(AnnotationDocument(first).state['brightness'], 170)
        self.assertEqual(window.brightness, 100)
        self.assertEqual(window._inline_controls['brightness'][0].value(), 100)
        self.assertEqual(AnnotationDocument(second).state['brightness'], 100)

    def test_actions_use_toolbar_and_undo_syncs_controls(self):
        self.image(10, 'a.png')
        window = self.window()
        with patch('planetary_studio.app.AdjustmentDialog') as dialog, patch('planetary_studio.app.SmoothingDialog') as smoothing:
            for action in (window.act_brightness, window.act_levels, window.act_sharpen, window.act_smooth):
                action.trigger()
            dialog.assert_not_called()
            smoothing.assert_not_called()
        window._inline_controls['gamma'][0].setValue(150)
        window._flush_inline_adjustments()
        window._undo_annotation()
        self.assertEqual(window.gamma, 1)
        self.assertEqual(window._inline_controls['gamma'][0].value(), 100)
        window._undo_annotation(redo=True)
        self.assertEqual(window._inline_controls['gamma'][0].value(), 150)
