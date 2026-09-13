import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.test_download_navigation as navigation
from PIL import Image
from PySide6.QtWidgets import QDialog

from planetary_studio.app import MainWindow
from planetary_studio.collections.missions import MissionRegistry
from planetary_studio.ui.mission_settings import MissionSettingsDialog


class MissionTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_migration_keeps_curiosity_and_builds_planet_mission_paths(self):
        state = {'source': 'curiosity', 'root': str(self.root), 'download_start_sol': 1400}
        registry = MissionRegistry(state)
        registry.library_root = str(self.root / 'Library')
        self.assertEqual(registry.folder_for('curiosity'), self.root)
        self.assertEqual(registry.folder_for('perseverance'), self.root / 'Library' / 'marte' / 'missions' / 'perseverance')
        self.assertEqual(registry.profiles['curiosity']['start_sol'], 1400)
        self.assertTrue(registry.profiles['curiosity']['auto_download'])
        self.assertTrue(registry.source_for('perseverance').supports_downloads)
        self.assertFalse((self.root / 'Library').exists())

    def test_custom_missions_roundtrip_and_folder_collision_validation(self):
        registry = MissionRegistry()
        registry.library_root = str(self.root)
        first = registry.add_custom('Lua', 'Minha missão')
        registry.profiles[first]['archive_url'] = 'https://example.org/images'
        restored = MissionRegistry({'mission_config': registry.serialize()})
        self.assertEqual(restored.folder_for(first), self.root / 'lua' / 'missions' / 'minha missão')
        self.assertEqual(restored.profiles[first]['archive_url'], 'https://example.org/images')
        second = restored.add_custom('Lua', 'Outra missão')
        restored.profiles[second]['folder_override'] = str(restored.folder_for(first))
        with self.assertRaises(ValueError):
            restored.validate()

    def test_dialog_cancel_does_not_change_configuration_and_save_keeps_selection(self):
        registry = MissionRegistry({'root': str(self.root)})
        original = registry.serialize()
        dialog = MissionSettingsDialog(registry, 'perseverance')
        self.addCleanup(dialog.close)
        dialog.base_folder.setText(str(self.root / 'Images'))
        self.assertIn('perseverance', dialog.path_preview.text())
        self.assertTrue(dialog.auto_download.isEnabled())
        self.assertEqual(registry.serialize(), original)
        dialog._save(open_selected=True)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.open_mission_id, 'perseverance')
        self.assertEqual(registry.serialize(), original)

    def test_two_local_missions_keep_separate_paths_and_sessions(self):
        self.image(10, 'curiosity.png')
        window = self.window()
        window.missions.library_root = str(self.root / 'Library')
        moon_id = window.missions.add_custom('Lua', 'Lunar Test')
        for mission_id in ('marte_spirit', moon_id):
            folder = window.missions.folder_for(mission_id) / '2026' / '09' / '07'
            folder.mkdir(parents=True)
            for filename in ('first.png', 'second.png'):
                Image.new('RGB', (80, 60), 'gray').save(folder / filename)
        with patch('requests.Session.get', side_effect=AssertionError('No network for local missions')):
            window._choose_source('marte_spirit')
            window._next_image()
            selected = window.current_path
            window._choose_source(moon_id)
            self.assertEqual(window.current_path.name, 'first.png')
            self.assertIn('lunar test', str(window.current_path))
            window._choose_source('marte_spirit')
            self.assertEqual(window.current_path, selected)
            self.assertFalse(window.act_download_now.isEnabled())
        state = window._build_state()
        reopened = MainWindow(window.root, state)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.source.id, 'marte_spirit')
        self.assertEqual(reopened.current_path, selected)
        self.assertIn(moon_id, reopened.missions.profiles)

    def test_auto_download_setting_is_per_mission(self):
        self.image(10, 'curiosity.png')
        window = self.window()
        window.missions.profiles['curiosity']['auto_download'] = False
        with patch('planetary_studio.app.QTimer.singleShot') as timer:
            window._activate_mission('curiosity', self.root)
        self.assertFalse(any(call.args[0] == 100 for call in timer.call_args_list))
        window.missions.profiles['curiosity']['auto_download'] = True
        with patch('planetary_studio.app.QTimer.singleShot') as timer:
            window._activate_mission('curiosity', self.root)
        self.assertTrue(any(call.args[0] == 100 for call in timer.call_args_list))

    def test_configured_download_uses_only_selected_mission_folder(self):
        registry = MissionRegistry()
        registry.library_root = str(self.root)
        destination = registry.folder_for('curiosity')
        worker = registry.source_for('curiosity').create_downloader(destination, only_sol=5)
        self.assertEqual(worker.root, self.root / 'marte' / 'missions' / 'curiosity')
        self.assertEqual(worker._folder_for_sol(5), self.root / 'marte' / 'missions' / 'curiosity' / 'SOL5')
        worker.session.close()

    def test_toolbar_selects_mission_without_folder_prompt(self):
        self.image(10, 'original.png')
        window = self.window()
        window.missions.library_root = str(self.root / 'Library')
        index = window.mission_selector.findData('perseverance')
        with patch('planetary_studio.app.QFileDialog.getExistingDirectory', side_effect=AssertionError('Unexpected folder prompt')):
            window._select_mission_from_toolbar(index)
        self.assertEqual(window.source.id, 'perseverance')
        self.assertEqual(window.mission_selector.currentData(), 'perseverance')
        self.assertEqual(window.root, self.root / 'Library' / 'marte' / 'missions' / 'perseverance')
        self.assertTrue(window.root.is_dir())

    def test_enabling_auto_download_starts_current_mission(self):
        self.image(10, 'original.png')
        window = self.window()
        window.missions.profiles['curiosity']['auto_download'] = False
        changed = copy.deepcopy(window.missions)
        changed.profiles['curiosity']['auto_download'] = True
        with patch('planetary_studio.app.MissionSettingsDialog') as dialog_type, patch('planetary_studio.app.QTimer.singleShot') as timer:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.registry = changed
            dialog.open_mission_id = None
            window._configure_missions()
        self.assertTrue(any(call.args == (100, window._start_downloader) for call in timer.call_args_list))

    def test_config_change_preserves_existing_files(self):
        path = self.image(10, 'original.png')
        window = self.window()
        original = path.read_bytes()
        changed = copy.deepcopy(window.missions)
        changed.library_root = str(self.root / 'NewLibrary')
        changed.profiles['curiosity']['folder_override'] = ''
        with patch('planetary_studio.app.MissionSettingsDialog') as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.registry = changed
            dialog.open_mission_id = 'curiosity'
            window._configure_missions()
        self.assertEqual(window.root, self.root / 'NewLibrary' / 'marte' / 'missions' / 'curiosity')
        self.assertTrue(window.root.is_dir())
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()