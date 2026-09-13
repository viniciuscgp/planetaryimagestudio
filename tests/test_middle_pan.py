import unittest
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtGui import QMouseEvent,QPixmap
from PySide6.QtWidgets import QApplication
from planetary_studio.app import ImageView

class MiddlePanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def event(self,view,kind,x,y,button,buttons):
        event=QMouseEvent(kind,QPointF(x,y),QPointF(x,y),button,buttons,Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(),event)
    def test_middle_drag_pans_without_drawing_for_every_tool(self):
        view=ImageView();self.addCleanup(view.close);view.resize(420,320)
        pixmap=QPixmap(2000,1500);pixmap.fill(Qt.GlobalColor.gray)
        view.set_pixmap(pixmap,fit=False);view.show();view.actual_size();self.app.processEvents()
        emitted=[];view.drawing_event.connect(lambda phase,point:emitted.append(phase))
        for tool in ('pan','select','pencil','circle','text','region'):
            with self.subTest(tool=tool):
                view.drawing_tool=tool;view.horizontalScrollBar().setValue(500);view.verticalScrollBar().setValue(500)
                before=(view.horizontalScrollBar().value(),view.verticalScrollBar().value());transform=view.transform();emitted.clear()
                self.event(view,QEvent.Type.MouseButtonPress,100,100,Qt.MouseButton.MiddleButton,Qt.MouseButton.MiddleButton)
                self.event(view,QEvent.Type.MouseMove,140,125,Qt.MouseButton.NoButton,Qt.MouseButton.MiddleButton)
                self.event(view,QEvent.Type.MouseButtonRelease,140,125,Qt.MouseButton.MiddleButton,Qt.MouseButton.NoButton)
                self.assertEqual(view.horizontalScrollBar().value(),before[0]-40)
                self.assertEqual(view.verticalScrollBar().value(),before[1]-25)
                self.assertEqual(view.drawing_tool,tool);self.assertFalse(view._middle_panning)
                self.assertEqual(emitted,[]);self.assertEqual(view.transform(),transform)
        view.drawing_tool='pencil'
        self.event(view,QEvent.Type.MouseButtonPress,100,100,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton)
        self.event(view,QEvent.Type.MouseButtonRelease,100,100,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)
        self.assertEqual(emitted,['press','release'])

if __name__=='__main__':unittest.main()