"""Rendered-document navigation/accessibility contracts; no AI output is simulated."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tempfile
import unittest


class Document(HTMLParser):
    def __init__(self,html):
        super().__init__()
        self.identifiers=[]
        self.references=[]
        self.story_links=[]
        self.pages=[]
        self.feed(html)

    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        if attrs.get('id'):
            self.identifiers.append(attrs['id'])
        if tag=='label' and attrs.get('for'):
            self.references.append(attrs['for'])
        if attrs.get('data-focus-setting'):
            self.references.append(attrs['data-focus-setting'])
        if attrs.get('data-story-link'):
            self.story_links.append(attrs['data-story-link'])
        if attrs.get('data-page'):
            self.pages.append(attrs['data-page'])


@unittest.skipUnless(importlib.util.find_spec('flask'),'Flask is not installed')
class ProductFrontendTests(unittest.TestCase):
    def setUp(self):
        import app
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_data,self.old_store=app.DATA,app.STORE
        self.addCleanup(setattr,app,'DATA',self.old_data)
        self.addCleanup(setattr,app,'STORE',self.old_store)
        app.DATA=Path(self.tmp.name)
        app.STORE=app.SQLiteStore(app.DATA/'test.sqlite3')
        self.client=app.create_app().test_client()

    def test_home_preserves_all_views_and_has_valid_navigation_and_form_targets(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        document=Document(response.get_data(as_text=True))
        self.assertEqual(len(document.identifiers),len(set(document.identifiers)),'Duplicate IDs break view and form bindings')
        self.assertEqual(set(document.pages),{'home','overview','analysis','tracking','helmets','speed','events','analytics','cameras','settings'})
        for target in document.references+document.story_links:
            with self.subTest(target=target):
                self.assertIn(target,document.identifiers)
        self.assertTrue({'story-intelligence','story-context','story-tracking','story-calibration','story-screening',
                         'story-review','story-workflow','story-history','story-responsibility'}.issubset(document.identifiers))
        for identifier in ('analysis-form','video-file','calibration-file','run-button','session-select','event-list','event-detail','track-detail'):
            self.assertIn(identifier,document.identifiers)
        self.assertIn('not analysis output',response.get_data(as_text=True))

    def test_product_assets_and_login_load_through_flask_with_no_external_asset_dependency(self):
        for path,mime in (('/static/premium.css','text/css'),('/static/premium.js','javascript'),('/static/images/road-night.jpg','image/jpeg')):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn(mime,response.mimetype)
                if path.endswith('.jpg'):
                    self.assertTrue(response.data.startswith(b'\xff\xd8'))
                response.close()
        login=self.client.get('/login')
        self.assertEqual(login.status_code,200)
        self.assertIn('/static/premium.css',login.get_data(as_text=True))
        self.assertIn('name="csrf_token"',login.get_data(as_text=True))
