import unittest

from PIL import Image

from planetary_studio.processing.image_adjustments import apply_adjustments, balance_colors
from planetary_studio.annotations.image_annotations import AnnotationDocument, empty_state, validate_state
import tests.test_inline_adjustments as inline_tests


class ColorBalanceTests(unittest.TestCase):
    def test_reduces_cast_without_mutating_source_or_alpha(self):
        image = Image.new('RGBA', (12, 8), (180, 160, 90, 137))
        before = image.tobytes()
        result = balance_colors(image)
        r, g, b, a = result.getpixel((0, 0))
        self.assertLess(max(r, g, b) - min(r, g, b), 90)
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.getchannel('A').tobytes(), image.getchannel('A').tobytes())
        self.assertEqual(image.tobytes(), before)
        self.assertEqual(apply_adjustments(image, empty_state()).tobytes(), before)

    def test_neutral_black_and_transparent_images_are_unchanged(self):
        for color in ((100, 100, 100, 255), (0, 0, 0, 255), (180, 160, 90, 0)):
            image = Image.new('RGBA', (4, 4), color)
            self.assertEqual(balance_colors(image).tobytes(), image.tobytes())

    def test_old_state_defaults_to_disabled(self):
        state = empty_state()
        del state['color_balance']
        validate_state(state)
        self.assertFalse(state['color_balance'])


class ColorBalanceWindowTests(unittest.TestCase):
    setUpClass = classmethod(inline_tests.InlineAdjustmentTests.setUpClass.__func__)
    setUp = inline_tests.InlineAdjustmentTests.setUp
    image = inline_tests.InlineAdjustmentTests.image
    window = inline_tests.InlineAdjustmentTests.window

    def test_toggle_persistence_undo_reset_and_navigation(self):
        first = self.image(10, 'a.png')
        self.image(10, 'b.png')
        original = first.read_bytes()
        window = self.window()
        window.image_view.scale(2, 2)
        transform = window.image_view.transform()
        window.act_balance.trigger()
        self.assertTrue(AnnotationDocument(first).state['color_balance'])
        self.assertEqual(window.image_view.transform(), transform)
        window._undo_annotation()
        self.assertFalse(window.act_balance.isChecked())
        window._undo_annotation(redo=True)
        self.assertTrue(window.act_balance.isChecked())
        window.thumb_list.setCurrentRow(1)
        self.assertFalse(window.color_balance)
        window.thumb_list.setCurrentRow(0)
        self.assertTrue(window.color_balance)
        window.act_balance.trigger()
        self.assertFalse(window.color_balance)
        window.act_balance.trigger()
        window._reset_adjustments()
        self.assertFalse(AnnotationDocument(first).state['color_balance'])
        self.assertEqual(first.read_bytes(), original)
