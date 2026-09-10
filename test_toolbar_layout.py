import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar
from PySide6.QtTest import QTest
from app import MainWindow
import test_download_navigation as navigation


class ToolbarLayoutTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_shortcuts_steps_and_icon_preference(self):
        self.image(10, 'first.png')
        window = self.window()
        window.show()
        window.activateWindow()
        window.image_view.setFocus()
        self.app.processEvents()
        for key, tool in ((Qt.Key.Key_O, 'ellipse'), (Qt.Key.Key_L, 'pencil'), (Qt.Key.Key_T, 'text')):
            QTest.keyClick(window.image_view, key)
            self.assertEqual(window.image_view.drawing_tool, tool)
        QTest.keyClick(window.image_view, Qt.Key.Key_E)
        self.assertTrue(window.color_balance)
        QTest.keyClick(window.image_view, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.rotation, 90)
        QTest.keyClick(window.image_view, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.rotation, 0)
        for slider, spin, widget, toolbar, factor in window._inline_controls.values():
            before = spin.value()
            spin.stepUp()
            self.assertAlmostEqual(spin.value(), min(spin.maximum(), before + 2 / factor))
            self.assertEqual(slider.singleStep(), 2)
        window._flush_inline_adjustments()
        window.act_toolbar_text.setChecked(False)
        for name in ('main_toolbar', 'drawing_toolbar', 'selection_toolbar'):
            bar = window.findChild(QToolBar, name)
            self.assertEqual(bar.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
            for action in bar.actions():
                if not action.isSeparator() and bar.widgetForAction(action).__class__.__name__ == 'QToolButton':
                    self.assertFalse(action.icon().isNull(), action.text())
        reopened = MainWindow(self.root, window._build_state())
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.act_toolbar_text.isChecked())
        self.assertEqual(reopened.findChild(QToolBar, 'main_toolbar').toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)

    def test_toolbar_positions_breaks_and_visibility_are_restored(self):
        self.image(10, 'first.png')
        window = self.window()
        window.show()
        drawing = window.findChild(QToolBar, 'drawing_toolbar')
        details = window.findChild(QToolBar, 'inline_adjustments_4')
        window.addToolBar(Qt.ToolBarArea.BottomToolBarArea, drawing)
        details.hide()
        selection = window.findChild(QToolBar, 'selection_toolbar')
        window.insertToolBarBreak(selection)
        state = window._build_state()
        reopened = MainWindow(self.root, state)
        self.addCleanup(reopened.close)
        reopened.show()
        self.app.processEvents()
        self.assertEqual(reopened.sol_list.count(), 1)
        self.assertEqual(reopened.toolBarArea(reopened.findChild(QToolBar, 'drawing_toolbar')),
                         Qt.ToolBarArea.BottomToolBarArea)
        self.assertTrue(reopened.findChild(QToolBar, 'inline_adjustments_4').isHidden())
        self.assertTrue(reopened.toolBarBreak(reopened.findChild(QToolBar, 'selection_toolbar')))
        names = [bar.objectName() for bar in reopened.findChildren(QToolBar)]
        self.assertTrue(all(names))
        self.assertEqual(len(names), len(set(names)))
