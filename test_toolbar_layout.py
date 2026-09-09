import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar
from app import MainWindow
import test_download_navigation as navigation


class ToolbarLayoutTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

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
