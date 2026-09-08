import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from sources.archives import (ArchiveWorker, ArchiveSource, ArchiveProvider, HiriseProvider, LrocProvider,
                              EsaHrscProvider, KaguyaProvider, collection_id, links, STATE_FILE)
from sources.perseverance import PerseveranceWorker
from missions import MissionRegistry
import test_download_navigation as navigation

class FakeProvider(ArchiveProvider):
    calls=[]
    def records(self,cursor):
        self.calls.append(dict(cursor))
        for i in range(cursor.get('index',0),3):
            yield {'folder':f'OBS_{i}','page':'https://example.org/observation','urls':[f'https://example.org/{i}.png']},{'index':i+1}

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        FakeProvider.calls=[]

    def worker(self,**kwargs):
        return ArchiveWorker(self.root,FakeProvider,batch_size=1,**kwargs)

    @staticmethod
    def download(key,url,dest,name):
        Image.new('RGB',(30,20),'blue').save(dest)
        return True

    def test_batch_checkpoints_and_restart_skip_existing(self):
        for expected in (1,2):
            w=self.worker()
            with patch.object(w,'_download_file',side_effect=self.download) as download:
                w.run()
            self.assertEqual(download.call_count,1)
            state=json.loads((self.root/STATE_FILE).read_text())
            self.assertEqual(state['cursor'],{'index':expected})
        w=self.worker(start_sol=0)
        with patch.object(w,'_download_file',side_effect=self.download) as download:
            w.run()
        download.assert_not_called()
        self.assertTrue((self.root/'OBS_0'/'0.png.source.json').exists())

    def test_failure_does_not_advance_and_retry_downloads_pending(self):
        w=self.worker(); errors=[];w.failed.connect(errors.append)
        with patch.object(w,'_download_file',side_effect=OSError('network')):
            w.run()
        self.assertTrue(errors)
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text())['cursor'],{})
        w=self.worker()
        with patch.object(w,'_download_file',side_effect=self.download):w.run()
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text())['cursor'],{'index':1})

    def test_html_instead_of_image_is_not_accepted(self):
        w=self.worker(); errors=[];w.failed.connect(errors.append)
        def bad(key,url,dest,name):dest.write_text('<html>Unavailable</html>')
        with patch.object(w,'_download_file',side_effect=bad):w.run()
        self.assertTrue(errors)
        self.assertFalse((self.root/'OBS_0'/'0.png').exists())
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text())['cursor'],{})

    def test_cancel_keeps_observation_pending(self):
        w=self.worker()
        def cancel(*args):w.stop();raise InterruptedError()
        with patch.object(w,'_download_file',side_effect=cancel):w.run()
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text())['cursor'],{})

    def test_selected_observation_does_not_move_catalog_cursor(self):
        w=self.worker()
        with patch.object(w,'_download_file',side_effect=self.download):w.run()
        state=json.loads((self.root/STATE_FILE).read_text())
        w=self.worker(only_sol=collection_id('OBS_0'))
        with patch.object(w,'_download_file') as download:w.run()
        download.assert_not_called()
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text())['cursor'],state['cursor'])

    def test_collection_ids_stay_stable_when_new_folders_arrive(self):
        (self.root/'OBS_1').mkdir();source=ArchiveSource()
        before=source.list_collections(self.root)
        (self.root/'OBS_0').mkdir()
        self.assertIn(before[0],source.list_collections(self.root))

    def test_perseverance_complete_sol_ignores_pagination(self):
        w=PerseveranceWorker(self.root);self.addCleanup(w.session.close)
        items=[{'sol':5,'image_files':{'full_res':f'https://example.org/{i}.png'}} for i in range(174)]
        with patch.object(w,'query',return_value={'images':items,'num_images':174}) as query:
            self.assertEqual(len(w._sol_items(5)),174)
        self.assertEqual(query.call_count,1)
        self.assertEqual(w._image_url({'url':'thumb.jpg','image_files':{'full_res':'full.png'}}),'full.png')

    def test_perseverance_rejects_wrong_sol_or_repeated_page(self):
        w=PerseveranceWorker(self.root);self.addCleanup(w.session.close)
        with patch.object(w,'query',return_value={'images':[{'sol':6}]}):
            with self.assertRaises(RuntimeError):w._sol_items(5)
        items=[{'sol':5,'image_files':{'full_res':f'https://example.org/{i}.png'}} for i in range(100)]
        with patch.object(w,'query',return_value={'images':items,'total_results':300}):
            with self.assertRaises(RuntimeError):w._sol_items(5)

    def test_hirise_parser_uses_archive_jpg_and_next_cursor(self):
        w=self.worker();p=HiriseProvider(w)
        with patch.object(p,'text',side_effect=['<a href="../ESP_093796_2260">image</a>', '<a href="https://hirise-pds.lpl.arizona.edu/PDS/A_RED.abrowse.jpg">Full</a><img src="thumb.jpg">']):
            record,cursor=next(p.records({}))
        self.assertEqual(record['urls'],['https://hirise-pds.lpl.arizona.edu/PDS/A_RED.abrowse.jpg'])
        self.assertEqual(cursor,{'page':1,'index':1})
        w.session.close()

    def test_kaguya_parser_skips_video_and_small_browse(self):
        w=self.worker();p=KaguyaProvider(w)
        with patch.object(p,'text',side_effect=['<a href="200906/">month</a>', '<a href="sh_20090610T181859_ti1/">still</a><a href="sh_20090610T181900_tm8/">movie</a>', '<a href="frame_bl.jpg">frame</a>']):
            record,cursor=next(p.records({}))
        self.assertIn('/browse/large/',record['urls'][0])
        self.assertEqual(cursor,{'month':0,'index':1})
        w.session.close()

    def test_lroc_parser_skips_calibration_and_uses_ptif(self):
        w=self.worker();p=LrocProvider(w)
        with patch.object(p,'text',side_effect=['<a href="/lroc/thumbnails?camera=NAC&amp;phase=ESM4">NAC</a>', '<a href="/lroc/view_lroc/EDR/C123LE">calibration</a><a href="/lroc/view_lroc/EDR/M123LE">observation</a>', '<a href="//pds.lroc.im-ldi.com/EXTRAS/M123LC_pyr.tif">CDR PTIF</a>']):
            record,cursor=next(p.records({}))
        self.assertEqual(record['folder'],'M123LE')
        self.assertTrue(record['urls'][0].startswith('https://'))
        w.session.close()

    def test_esa_parser_filters_to_hrsc_full_jpg(self):
        w=self.worker();p=EsaHrscProvider(w)
        with patch.object(p,'text',side_effect=['<a href="/ESA_Multimedia/Images/2026/01/Crater">image</a>','<div class="modal__tab-description">HRSC</div> <a href="/var/esa/storage/images/Crater.jpg">original</a><a href="/var/esa/storage/images/Crater_card_medium.jpg">thumb</a>']):
            record,cursor=next(p.records({}))
        self.assertEqual(record['urls'],['https://www.esa.int/var/esa/storage/images/Crater.jpg'])
        w.session.close()

class ArchiveUiTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def test_archive_controls_and_downloads_do_not_change_selection(self):
        self.image(1,'first.png');window=self.window()
        window.missions.library_root=str(self.root/'Library')
        key='marte_mars_reconnaissance_orbiter'
        folder=window.missions.folder_for(key)/'ESP_000001_0001';folder.mkdir(parents=True)
        Image.new('RGB',(30,20),'blue').save(folder/'selected.png')
        window._choose_source(key)
        selected=window.current_path
        self.assertEqual(selected,folder/'selected.png')
        self.assertFalse(window.source.uses_sols)
        self.assertTrue(window.download_start_sol.isHidden())
        self.assertIn('lote',window.download_now_button.text())
        added=folder.parent/'ESP_000002_0001';added.mkdir()
        window._on_download_sol_created(collection_id(added.name),str(added))
        self.assertEqual(window.current_path,selected)
        self.assertEqual(window._collection_text(collection_id(added.name)),added.name)

    def test_only_validated_missions_enable_downloads(self):
        registry=MissionRegistry()
        for key in ['curiosity','perseverance','marte_mars_reconnaissance_orbiter','marte_mars_express','lua_lunar_reconnaissance_orbiter','lua_kaguya_selene']:
            self.assertTrue(registry.source_for(key).supports_downloads,key)
        self.assertFalse(registry.source_for('lua_chandrayaan_2').supports_downloads)
        self.assertFalse(registry.source_for('lua_chang_e_4').supports_downloads)

if __name__=='__main__':unittest.main()