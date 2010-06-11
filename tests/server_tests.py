#!/usr/bin/python2.5
# Copyright 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""End-to-end application testing.  This starts up an appserver and tests it.

Usage: server_tests.py"""

import datetime
import inspect
import os
import re
import scrape
import signal
import subprocess
import sys
import traceback
import unittest

# Make scripts/remote_api.py importable.
TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(PROJECT_DIR, 'scripts')
sys.path.append(SCRIPTS_DIR)

import remote_api
from model import *
import reveal


NOTE_STATUS_OPTIONS = [
  '',
  'information_sought',
  'is_note_author',
  'believed_alive',
  'believed_missing',
  'believed_dead'
]


class NotRunningError(Exception):
  """The Appserver aborted prematurely."""
  pass


class AppServerProcess:
  """Encapsulates a subprocess running a dev_appserver."""

  def __init__(self, port):
    cmd = os.path.join(remote_api.APPENGINE_DIR, 'dev_appserver.py')
    self.datastore_path = '/tmp/dev_appserver.datastore.%d' % os.getpid()
    self._process = subprocess.Popen(
        args=[cmd, remote_api.APP_DIR, '--port=%s' % port, '--clear_datastore',
              '--datastore_path=%s' % self.datastore_path, '--require_indexes'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

  def wait_readiness(self):
    """This waits until the subprocess logs its readiness."""
    # TODO: Add a timeout.
    stderr = ['']
    line = ''
    while 'Running application ' not in line:
      line = self._process.stderr.readline()
      stderr.append(line)
      if not line:  # Reached EOF
        print >>sys.stderr, '\n'.join(stderr)
        raise NotRunningError
      if 'Running application ' in line:
        return

  def terminate(self, status=0):
    if self._process.poll() is None:
      # Kill appserver without logging an error
      os.kill(self._process.pid, signal.SIGKILL)
    else:
      # appserver already died, find out why
      status = self._process.returncode

    (stdout, stderr) = self._process.communicate()
    for line in stdout.split('\n') + stderr.split('\n'):
      if line.startswith('INFO'):
        # Currently no way to set the logging level in the appserver
        # So filter out logging.info() by hand
        continue
      if line.startswith('ERROR') or line.startswith('CRITICAL'):
        # Exit with error status
        status = 1
      print >>sys.stderr, line
    if os.path.exists(self.datastore_path):
      os.unlink(self.datastore_path)

    sys.exit(status)


def get_test_data(filename):
  return open(os.path.join(TESTS_DIR, filename)).read()

def reset_data():
  """Reset the datastore to a known state, populated with test data."""
  db.delete(Authorization.all())
  db.delete(Person.all())
  db.delete(Note.all())
  db.delete(Secret.all())
  db.put(Authorization(auth_key='test_key', domain='test.google.com'))
  db.put(Authorization(auth_key='other_key', domain='other.google.com'))

def all_by_class(region, class_name):
  """Return all elements of the given region that have the given class name."""
  return region.all(**{'class': class_name})

def first_by_class(region, class_name):
  """Return the first element of the given region that has the given class name.

  Unlike Region.first(), this method returns None when no such element exists
  rather than raising an error.
  """
  try:
    return region.first(**{'class': class_name})
  except scrape.ScrapeError:
    return None

def assert_params_conform(url, required_params=None, forbidden_params=None):
  """Enforces the presence and non-presence of URL parameters.

  If required_params or forbidden_params is set, this function asserts that the
  given URL contains or does not contain those parameters, respectively.
  """
  required_params = required_params or {}
  forbidden_params = forbidden_params or {}

  for key, value in required_params.iteritems():
    param_regex = re.compile(r'\b%s=%s\b' %
                             (re.escape(key), re.escape(value)))
    assert param_regex.search(url), 'URL %s must contain %s=%s' % (
        url, key, value)

  for key, value in forbidden_params.iteritems():
    param_regex = re.compile(r'\b%s=%s\b' %
                             (re.escape(key), re.escape(value)))
    assert not param_regex.search(url), 'URL %s must not contain %s=%s' % (
        url, key, value)


class ReadOnlyTests(unittest.TestCase):
  """Tests that don't modify data go here.  They'll run much faster than
  tests in ReadWriteTests.  These tests can expect the data to be populated
  with standard test data."""
  verbose = 0

  def setUp(self):
    """Sets up a scrape Session for each test."""
    # See http://zesty.ca/scrape for documentation on scrape.
    self.s = scrape.Session(verbose=self.verbose)

  def test_main(self):
    """Check the main page with no language specified."""
    doc = self.s.go('http://%s/' % self.hostport)
    assert 'I\'m looking for someone' in doc.text

  def test_main_english(self):
    """Check the main page with English language specified."""
    doc = self.s.go('http://%s/?lang=en' % self.hostport)
    assert 'I\'m looking for someone' in doc.text

  def test_main_french(self):
    """Check the French main page."""
    doc = self.s.go('http://%s/?lang=fr' % self.hostport)
    assert 'Je recherche quelqu\'un' in doc.text

  def test_main_creole(self):
    """Check the Creole main page."""
    doc = self.s.go('http://%s/?lang=ht' % self.hostport)
    assert u'Mwen ap ch\u00e8che yon moun' in doc.text

  def test_language_links(self):
    """Check that the language links go to the translated main page."""
    doc = self.s.go('http://%s/' % self.hostport)

    doc = self.s.follow(u'Fran\u00e7ais')
    assert 'Je recherche quelqu\'un' in doc.text

    doc = self.s.follow(u'Krey\u00f2l')
    assert u'Mwen ap ch\u00e8che yon moun' in doc.text

    doc = self.s.follow(u'English')
    assert 'I\'m looking for someone' in doc.text

  def test_query(self):
    """Check the query page."""
    doc = self.s.go('http://%s/query' % self.hostport)
    button = doc.firsttag('input', type='submit')
    assert button['value'] == 'Search for this person'

    doc = self.s.go('http://%s/query?role=provide' % self.hostport)
    button = doc.firsttag('input', type='submit')
    assert button['value'] == 'Provide information about this person'

  def test_results(self):
    """Check the results page."""
    doc = self.s.go('http://%s/results?first_name=xy' % self.hostport)
    assert 'We have nothing' in doc.text

  def test_create(self):
    """Check the create page."""
    doc = self.s.go('http://%s/create' % self.hostport)
    assert 'Identify who you are looking for' in doc.text

    doc = self.s.go('http://%s/create?role=provide' % self.hostport)
    assert 'Identify who you have information about' in doc.text

  def test_view(self):
    """Check the view page."""
    doc = self.s.go('http://%s/view' % self.hostport)
    assert 'No person id was specified' in doc.text

  def test_multiview(self):
    """Check the multiview page."""
    doc = self.s.go('http://%s/multiview' % self.hostport)
    assert 'Compare these records' in doc.text

  def test_photo(self):
    """Check the photo page."""
    doc = self.s.go('http://%s/photo' % self.hostport)
    assert 'No photo id was specified' in doc.text

  def test_static(self):
    """Check that the static files are accessible."""
    doc = self.s.go('http://%s/static/no-photo.gif' % self.hostport)
    assert doc.content.startswith('GIF89a')

    doc = self.s.go('http://%s/static/style.css' % self.hostport)
    assert 'body {' in doc.content

  def test_embed(self):
    """Check the embed page."""
    doc = self.s.go('http://%s/embed' % self.hostport)
    assert 'Embedding' in doc.text

  def test_developers(self):
    """Check the developer instructions page."""
    doc = self.s.go('http://%s/developers' % self.hostport)
    assert 'Downloading Data' in doc.text

  def test_sitemap(self):
    """Check the sitemap generator."""
    doc = self.s.go('http://%s/sitemap' % self.hostport)
    assert '</sitemapindex>' in doc.content

    doc = self.s.go('http://%s/sitemap?shard_index=1' % self.hostport)
    assert '</urlset>' in doc.content


class ReadWriteTests(unittest.TestCase):
  """Tests that modify data in the datastore go here.  The contents of the
  datastore will be reset for each test."""
  verbose = 0

  def setUp(self):
    """Sets up a scrape Session for each test."""
    # See http://zesty.ca/scrape for documentation on scrape.
    self.s = scrape.Session(verbose=self.verbose)

  def tearDown(self):
    """Resets the contents of the datastore."""
    reset_data()

  def assert_error_deadend(self, page, *fragments):
    """Assert that the given page is a dead-end.

    Checks to make sure that there's an error message that contains the given
    fragments.  On failure, fail assertion.  On success, step back.
    """

    error_message = (first_by_class(page, 'error') or
                     first_by_class(page, 'instructions error'))
    assert error_message, 'Expecting an error message on in %s' % page
    for fragment in fragments:
      assert fragment in error_message.text, (
          '%s missing from error message' % fragment)
    self.s.back()

  # The verify_ functions below implement common fragments of the testing
  # workflow that are assembled below in the test_ methods.

  def verify_results_page(self, num_results, all_have=(), some_have=()):
    """Verifies conditions on the results page common to seeking and providing.

    Verifies that all of the results contain all of the strings in all_have and
    that at least one of the results has each of some_have.

    Precondition: the current session must be on the results page
    Postcondition: the current session is still on the results page
    """

    # Check that the results are as expected
    results_titles = all_by_class(self.s.doc, 'resultDataTitle')
    self.assertEqual(num_results, len(results_titles))
    for title in results_titles:
      for text in all_have:
        assert text in title.content, '%s must have %s' % (title.content, text)
    for text in some_have:
      assert any(text in title.content for title in results_titles), (
          'One of %s must have %s' % (results_titles, text))

  def verify_unsatisfactory_results(self):
    """Verifies the clicking the button at the bottom of the results page.

    Precondition: the current session must be on the results page
    Postcondition: the current session is on the create new record page
    """

    # Click the button to create a new record
    results_form = self.s.doc.first('form')
    assert 'Create a new record' in results_form.content, (
        'Expecting a "create" button in %s' % results_form)
    self.s.submit(results_form)

  def verify_create_form(self, prefilled_params=None, unfilled_params=None):
    """Verifies the behavior of the create form.

    Verifies that the form must contain prefilled_params (a dictionary) and may
    not have any defaults for unfilled_params.

    Precondition: the current session is on the create new record page
    Postcondition: the current session is still on the create new record page
    """

    create_form = self.s.doc.first('form')
    for key, value in (prefilled_params or {}).iteritems():
      self.assertEqual(create_form.params[key], value)
    for key in unfilled_params or ():
      assert not create_form.params[key]

    # Try to submit without filling in required fields
    self.assert_error_deadend(self.s.submit(create_form),
                              'required', 'try again')

  def verify_note_form(self):
    """Verifies the behavior of the add note form.

    Precondition: the current session is on a page with a note form.
    Postcondition: the current session is still on a page with a note form.
    """

    note_form = self.s.doc.first('form')
    assert 'Tell us the status of this person' in note_form.content
    self.assert_error_deadend(self.s.submit(note_form), 'required', 'try again')

  def verify_details_page(self, num_notes, details=None):
    """Verifies the content of the details page.

    Verifies that the details contain the given number of notes and the given
    details.

    Precondition: the current session is on the details page
    Postcondition: the current session is still on the details page
    """

    # Do not assert params.  By the time you reach the details page, you've lost
    # the difference between seekers and providers and the param is gone.

    details = details or {}
    details_page = self.s.doc

    # Person info is stored in matching 'label' and 'field' cells.
    fields = dict(zip(
        (label.text.strip() for label in all_by_class(details_page, 'label')),
        all_by_class(details_page, 'field')))
    for label, value in details.iteritems():
      self.assertEqual(fields[label].text.strip(), value)

    self.assertEqual(num_notes, len(all_by_class(details_page, 'view note')))

  def verify_click_search_result(self, n, url_test=lambda u: None):
    """Verifies clicking the nth search result.

    Also enforces the URL followed against the given assertion test.  The
    function should raise an AssertionError on failure.

    Precondition: the current session must be on the results page
    Postcondition: the current session is on the person details page
    """

    # Get the person ID of the first result and simulate clicking on it
    tracking = all_by_class(self.s.doc, 'tracking')[n]
    ids = re.compile('google\.com/person\.\d+').findall(tracking.text)
    self.assertEqual(len(ids), 1)

    result_row = tracking.enclosing('a')
    # Ensure that the onclick handler for this row enforces the necessary params
    url_test(result_row['href'])

    # Parse out the role so it can be preserved
    role = re.compile('role=(provide|seek)').search(
        result_row['href']).group()
    assert role

    details_page = self.s.go('http://%s/view?id=%s&role=%s' %
                             (self.hostport, ids[0], role))

  def verify_update_notes(self, found, note_body, author, **kwargs):
    """Verifies the process of adding a new note.

    Posts a new note with the given parameters.

    Precondition: the current session must be on the details page
    Postcondition: the current session is still on the details page
    """

    # Do not assert params.  By the time you reach the details page, you've lost
    # the difference between seekers and providers and the param is gone.

    details_page = self.s.doc
    num_initial_notes = len(all_by_class(details_page, 'view note'))
    note_form = details_page.first('form')

    params = dict(kwargs)
    params['found'] = (found and 'yes') or 'no'
    params['text'] = note_body
    params['author_name'] = author

    details_page = self.s.submit(note_form, **params)
    notes = all_by_class(details_page, 'view note')
    self.assertEqual(len(notes), num_initial_notes + 1)
    new_note_text = notes[-1].text
    for text in kwargs.values() + [note_body, author]:
      assert text in new_note_text, 'Note text \"%s\" missing \"%s\"' % (
          new_note_text, text)

    # Show this text if and only if the person has been found
    assert ('Missing person has been in contact with someone'
            in new_note_text) == found

  def test_seeking_someone_regular(self):
    """Follow the seeking someone flow on the regular-sized embed."""

    # Shorthand to assert the correctness of our URL
    def assert_params(url=None):
      assert_params_conform(
          url or self.s.url, {'role': 'seek'}, {'small': 'yes'})

    # Start on the home page and click the "I'm looking for someone" button
    self.s.go('http://%s/' % self.hostport)
    search_page = self.s.follow('I\'m looking for someone')
    search_form = search_page.first('form')
    assert 'Search for this person' in search_form.content

    # Try a search, which should yield no results.
    self.s.submit(search_form, first_name='_test_first_name')
    assert_params()
    self.verify_results_page(0)
    assert_params()
    self.verify_unsatisfactory_results()
    assert_params()
    self.verify_create_form(prefilled_params={'first_name': '_test_first_name'},
                            unfilled_params=('last_name',))

    # Submit the create form with minimal information.
    create_form = self.s.doc.first('form')
    self.s.submit(create_form,
                  last_name='_test_last_name',
                  author_name='_test_author_name')

    # For now, the date of birth should be hidden.
    assert 'birth' not in self.s.content.lower()

    self.verify_details_page(
        0, details={'Given name:': '_test_first_name',
                    'Family name:': '_test_last_name',
                    'Author\'s name:': '_test_author_name'})

    # Now the search should yield a result.
    self.s.submit(search_form, first_name='_test_first_name')
    assert_params()
    self.verify_results_page(1, all_have=(['_test_first_name']),
                             some_have=(['_test_first_name']))
    self.verify_click_search_result(0, assert_params)
    # set the person entry_date to something in order to make sure adding note
    # doesn't update
    person = Person.all().filter('first_name =', '_test_first_name').get()
    person.entry_date = datetime.datetime(2006, 6, 6, 6, 6, 6)
    db.put(person)
    self.verify_details_page(0)
    self.verify_note_form()
    self.verify_update_notes(False, '_test A note body', '_test A note author')
    self.verify_update_notes(
        True, '_test Another note body', '_test Another note author',
        last_known_location='Port-au-Prince')

    person = Person.all().filter('first_name =', '_test_first_name').get()
    assert person.entry_date == datetime.datetime(2006, 6, 6, 6, 6, 6)

    # Submit the create form with complete information
    self.s.submit(create_form,
                  author_name='_test_author_name',
                  author_email='_test_author_email',
                  author_phone='_test_author_phone',
                  clone='yes',
                  source_name='_test_source_name',
                  source_date='2001-01-01',
                  source_url='_test_source_url',
                  first_name='_test_first_name',
                  last_name='_test_last_name',
                  sex='female',
                  date_of_birth='1955',
                  age='52',
                  home_street='_test_home_street',
                  home_neighborhood='_test_home_neighborhood',
                  home_city='_test_home_city',
                  home_state='_test_home_state',
                  home_zip='_test_home_zip',
                  home_country='_test_home_country',
                  photo_url='_test_photo_url',
                  description='_test_description')

    self.verify_details_page(
        0, details={'Given name:': '_test_first_name',
                    'Family name:': '_test_last_name',
                    'Sex:': 'female',
                    # 'Date of birth:': '1955',  # currently hidden
                    'Age:': '52',
                    'Street name:': '_test_home_street',
                    'Neighborhood:': '_test_home_neighborhood',
                    'City:': '_test_home_city',
                    'Province or state:': '_test_home_state',
                    'Postal or zip code:': '_test_home_zip',
                    'Home country:': '_test_home_country',
                    'Author\'s name:': '_test_author_name',
                    'Author\'s phone number:': '(click to reveal)',
                    'Author\'s e-mail address:': '(click to reveal)',
                    'Original URL:': 'Link',
                    'Original posting date:': '2001-01-01 00:00 UTC',
                    'Original site name:': '_test_source_name'})

  def test_no_default_new_indexing(self):
    """make sure new search is off by default"""

    # Shorthand to assert the correctness of our URL
    def assert_params(url=None):
      assert_params_conform(
          url or self.s.url, {'role': 'seek'}, {'small': 'yes'})

    # Start on the home page and click the "I'm looking for someone" button
    self.s.go('http://%s/' % self.hostport)
    search_page = self.s.follow('I\'m looking for someone')
    search_form = search_page.first('form')
    assert 'Search for this person' in search_form.content

    # Try a search, which should yield no results.
    self.s.submit(search_form, first_name='eyal fink', last_name='knif laye')
    assert_params()
    self.verify_results_page(0)
    assert_params()
    self.verify_unsatisfactory_results()
    assert_params()
    self.verify_create_form(prefilled_params={'first_name': 'eyal fink',
                                              'last_name': 'knif laye'},
                            unfilled_params=())

     # Submit the create form with a valid first and last name
     # without new search param
    self.s.submit(self.s.doc.first('form'),
                  first_name='eyal fink',
                  last_name='knif laye',
                  author_name='author_name')
    # Make sure regular search doesn't use new indexing
    self.s.submit(search_form, first_name='fink')
    self.verify_results_page(0)
    # Make sure regular create works regular
    self.s.submit(search_form, first_name='eyal')
    self.verify_results_page(1, all_have=(['eyal fink']))

  def test_new_indexing(self):
    """First create new entry with new_search param then search for it"""

    # Shorthand to assert the correctness of our URL
    def assert_params(url=None):
      assert_params_conform(
          url or self.s.url, {'role': 'seek'}, {'small': 'yes'})

    # Start on the home page and click the "I'm looking for someone" button
    self.s.go('http://%s/' % self.hostport)
    search_page = self.s.follow('I\'m looking for someone')
    search_form = search_page.first('form')
    assert 'Search for this person' in search_form.content

    # Try a search, which should yield no results.
    self.s.submit(search_form, first_name='ABCD EFGH', last_name='IJKL MNOP')
    assert_params()
    self.verify_results_page(0)
    assert_params()
    self.verify_unsatisfactory_results()
    assert_params()
    self.verify_create_form(prefilled_params={'first_name': 'ABCD EFGH',
                                              'last_name': 'IJKL MNOP'},
                            unfilled_params=())

    # Submit the create form with a valid first and last name
    self.s.submit(self.s.doc.first('form'),
                  first_name='ABCD EFGH',
                  last_name='IJKL MNOP',
                  author_name='author_name')

    # Try a middle-name match.
    self.s.submit(search_form, first_name='EFGH', new_search='yes')
    self.verify_results_page(1, all_have=(['ABCD EFGH']))

    # Try a middle-name non-match.
    self.s.submit(search_form, first_name='ABCDEF', new_search='yes')
    self.verify_results_page(0)

    # Try a middle-name prefix match.
    self.s.submit(search_form, first_name='MNO', new_search='yes')
    self.verify_results_page(1, all_have=(['ABCD EFGH']))

    # Try a multiword match.
    self.s.submit(search_form, first_name='MNOP IJK ABCD EFG', new_search='yes')
    self.verify_results_page(1, all_have=(['ABCD EFGH']))

  def test_have_information_regular(self):
    """Follow the "I have information" flow on the regular-sized embed."""

    # Shorthand to assert the correctness of our URL
    def assert_params(url=None):
      assert_params_conform(
          url or self.s.url, {'role': 'provide'}, {'small': 'yes'})

    self.s.go('http://%s/' % self.hostport)
    search_page = self.s.follow('I have information about someone')
    search_form = search_page.first('form')
    assert 'I have information about someone' in search_form.content

    self.assert_error_deadend(self.s.submit(search_form),
                              'Enter the person\'s given and family names.')
    self.assert_error_deadend(
        self.s.submit(search_form, first_name='_test_first_name'),
        'Enter the person\'s given and family names.')

    self.s.submit(search_form,
                  first_name='_test_first_name',
                  last_name='_test_last_name')
    assert_params()
    # Because the datastore is empty, should go straight to the create page
    self.verify_create_form(prefilled_params={'first_name': '_test_first_name',
                                              'last_name': '_test_last_name'})
    self.verify_note_form()

    # Submit the create form with minimal information
    create_form = self.s.doc.first('form')
    self.s.submit(create_form,
                  last_name='_test_last_name',
                  author_name='_test_author_name',
                  text='_test A note body')

    self.verify_details_page(
        1, details={'Given name:': '_test_first_name',
                    'Family name:': '_test_last_name',
                    'Author\'s name:': '_test_author_name'})

    # Try the search again, and should get some results
    self.s.submit(search_form,
                  first_name='_test_first_name',
                  last_name='_test_last_name')
    assert_params()
    self.verify_results_page(
        1, all_have=('_test_first_name', '_test_last_name'))
    self.verify_click_search_result(0, assert_params)

    # For now, the date of birth should be hidden.
    assert 'birth' not in self.s.content.lower()
    self.verify_details_page(1)

    self.verify_note_form()
    self.verify_update_notes(False, '_test A note body', '_test A note author')
    self.verify_update_notes(
        True, '_test Another note body', '_test Another note author',
        last_known_location='Port-au-Prince')

    # Submit the create form with complete information
    self.s.submit(create_form,
                  author_name='_test_author_name',
                  author_email='_test_author_email',
                  author_phone='_test_author_phone',
                  clone='yes',
                  source_name='_test_source_name',
                  source_date='2001-01-01',
                  source_url='_test_source_url',
                  first_name='_test_first_name',
                  last_name='_test_last_name',
                  sex='male',
                  date_of_birth='1970-01',
                  age='30-40',
                  home_street='_test_home_street',
                  home_neighborhood='_test_home_neighborhood',
                  home_city='_test_home_city',
                  home_state='_test_home_state',
                  home_zip='_test_home_zip',
                  home_country='_test_home_country',
                  photo_url='_test_photo_url',
                  description='_test_description',
                  add_note='yes',
                  found='yes',
                  status='believed_alive',
                  email_of_found_person='_test_email_of_found_person',
                  phone_of_found_person='_test_phone_of_found_person',
                  last_known_location='_test_last_known_location',
                  text='_test A note body')

    self.verify_details_page(
        1, details={'Given name:': '_test_first_name',
                    'Family name:': '_test_last_name',
                    'Sex:': 'male',
                    # 'Date of birth:': '1970-01',  # currently hidden
                    'Age:': '30-40',
                    'Street name:': '_test_home_street',
                    'Neighborhood:': '_test_home_neighborhood',
                    'City:': '_test_home_city',
                    'Province or state:': '_test_home_state',
                    'Postal or zip code:': '_test_home_zip',
                    'Home country:': '_test_home_country',
                    'Author\'s name:': '_test_author_name',
                    'Author\'s phone number:': '(click to reveal)',
                    'Author\'s e-mail address:': '(click to reveal)',
                    'Original URL:': 'Link',
                    'Original posting date:': '2001-01-01 00:00 UTC',
                    'Original site name:': '_test_source_name'})

  def test_reveal(self):
    """Test the hiding and revealing of contact information in the UI."""
    db.put(Person(
        key_name='test.google.com/person.123',
        author_name='_reveal_author_name',
        author_email='_reveal_author_email',
        author_phone='_reveal_author_phone',
        entry_date=datetime.datetime.now(),
        first_name='_reveal_first_name',
        last_name='_reveal_last_name',
        sex='male',
        date_of_birth='1970-01-01',
        age='30-40',
    ))
    db.put(Note(
        key_name='test.google.com/note.456',
        author_name='_reveal_note_author_name',
        author_email='_reveal_note_author_email',
        author_phone='_reveal_note_author_phone',
        entry_date=datetime.datetime.now(),
        email_of_found_person='_reveal_email_of_found_person',
        phone_of_found_person='_reveal_phone_of_found_person',
        person_record_id='test.google.com/person.123',
    ))

    # All contact information should be hidden by default.
    doc = self.s.go('http://%s/view?id=%s' %
                    (self.hostport, 'test.google.com/person.123'))
    assert '_reveal_author_email' not in doc.content
    assert '_reveal_author_phone' not in doc.content
    assert '_reveal_note_author_email' not in doc.content
    assert '_reveal_note_author_phone' not in doc.content
    assert '_reveal_email_of_found_person' not in doc.content
    assert '_reveal_phone_of_found_person' not in doc.content

    # An invalid signature should not work.
    doc = self.s.go('http://%s/view?id=%s&signature=abc.1999999999' %
                    (self.hostport, 'test.google.com/person.123'))
    assert '_reveal_author_email' not in doc.content
    assert '_reveal_author_phone' not in doc.content
    assert '_reveal_note_author_email' not in doc.content
    assert '_reveal_note_author_phone' not in doc.content
    assert '_reveal_email_of_found_person' not in doc.content
    assert '_reveal_phone_of_found_person' not in doc.content

    # An expired signature should not work.
    signature = reveal.sign(u'view:test.google.com/person.123', -10)
    doc = self.s.go('http://%s/view?id=%s&signature=%s' %
                    (self.hostport, 'test.google.com/person.123', signature))
    assert '_reveal_author_email' not in doc.content
    assert '_reveal_author_phone' not in doc.content
    assert '_reveal_note_author_email' not in doc.content
    assert '_reveal_note_author_phone' not in doc.content
    assert '_reveal_email_of_found_person' not in doc.content
    assert '_reveal_phone_of_found_person' not in doc.content

    # Now supply a valid revelation signature.
    signature = reveal.sign(u'view:test.google.com/person.123', 10)
    doc = self.s.go('http://%s/view?id=%s&signature=%s' %
                    (self.hostport, 'test.google.com/person.123', signature))
    assert '_reveal_author_email' in doc.content
    assert '_reveal_author_phone' in doc.content
    assert '_reveal_note_author_email' in doc.content
    assert '_reveal_note_author_phone' in doc.content
    assert '_reveal_email_of_found_person' in doc.content
    assert '_reveal_phone_of_found_person' in doc.content

    # Start over.
    doc = self.s.go('http://%s/view?id=%s' %
                    (self.hostport, 'test.google.com/person.123'))
    assert '_reveal_author_email' not in doc.content
    assert '_reveal_author_phone' not in doc.content
    assert '_reveal_note_author_email' not in doc.content
    assert '_reveal_note_author_phone' not in doc.content
    assert '_reveal_email_of_found_person' not in doc.content
    assert '_reveal_phone_of_found_person' not in doc.content

    # This time, click through the reveal page flow to get the signature.
    doc = self.s.follow('(click to reveal)')
    doc = self.s.follow('sign in')
    button = doc.firsttag('input', value='Login')
    doc = self.s.submit(button)
    button = doc.firsttag('input', value='Proceed')
    doc = self.s.submit(button)
    assert '_reveal_author_email' in doc.content
    assert '_reveal_author_phone' in doc.content
    assert '_reveal_note_author_email' in doc.content
    assert '_reveal_note_author_phone' in doc.content
    assert '_reveal_email_of_found_person' in doc.content
    assert '_reveal_phone_of_found_person' in doc.content

    # All contact information should be hidden on the multiview page, too.
    doc = self.s.go('http://%s/multiview?id1=%s' %
                    (self.hostport, 'test.google.com/person.123'))
    assert '_reveal_author_email' not in doc.content
    assert '_reveal_author_phone' not in doc.content
    assert '_reveal_note_author_email' not in doc.content
    assert '_reveal_note_author_phone' not in doc.content
    assert '_reveal_email_of_found_person' not in doc.content
    assert '_reveal_phone_of_found_person' not in doc.content

    # Now supply a valid revelation signature.
    signature = reveal.sign(u'multiview:test.google.com/person.123', 10)
    doc = self.s.go('http://%s/multiview?id1=%s&signature=%s' %
                    (self.hostport, 'test.google.com/person.123', signature))
    assert '_reveal_author_email' in doc.content
    assert '_reveal_author_phone' in doc.content
    # Notes are not shown on the multiview page.

  def test_note_status(self):
    """Test the posting and viewing of the note status field in the UI."""
    status_class = re.compile(r'\bstatus\b')

    # Check that the right status options appear on the create page.
    doc = self.s.go('http://%s/create?role=provide' % self.hostport)
    note = doc.first(**{'class': 'note input'})
    options = note.first('select', name='status').all('option')
    assert len(options) == len(NOTE_STATUS_OPTIONS)
    for option, text in zip(options, NOTE_STATUS_OPTIONS):
      assert text in option.attrs['value']

    # Create a record with no status and get the new record's ID.
    form = doc.first('form')
    doc = self.s.submit(form, first_name='_test_first', last_name='_test_last',
      author_name='_test_author', text='_test_text')
    view_url = self.s.url

    # Check that the right status options appear on the view page.
    doc = self.s.go(view_url)
    note = doc.first(**{'class': 'note input'})
    options = note.first('select', name='status').all('option')
    assert len(options) == len(NOTE_STATUS_OPTIONS)
    for option, text in zip(options, NOTE_STATUS_OPTIONS):
      assert text in option.attrs['value']

    # Set the status in a note and check that it appears on the view page.
    form = doc.first('form')
    self.s.submit(form, author_name='_test_author2', text='_test_text',
                  status='believed_alive')
    doc = self.s.go(view_url)
    note = doc.last(**{'class': 'view note'})
    assert 'believed_alive' in note.content
    assert 'believed_dead' not in note.content

    # Set status to is_note_author, but don't check found.
    self.s.submit(form, author_name='_test_author',
                  text='_test_text',
                  status='is_note_author')
    self.assert_error_deadend(self.s.submit(form, author_name='_test_author',
                                            text='_test_text',
                                            status='is_note_author'),
                              'in contact', 'Status of this person')

  def test_api_write_pfif_1_2(self):
    """Post a single entry as PFIF 1.2 using the upload API."""
    data = get_test_data('test.pfif-1.2.xml')
    self.s.go('http://%s/api/write?key=test_key' % self.hostport, data=data,
              type='application/xml')
    person = Person.get_by_key_name('test.google.com/person.21009')
    assert person.first_name == u'_test_first_name'
    assert person.last_name == u'_test_last_name'
    assert person.sex == u'female'
    assert person.date_of_birth == u'1970-01'
    assert person.age == u'35-45'
    assert person.author_name == u'_test_author_name'
    assert person.author_email == u'_test_author_email'
    assert person.author_phone == u'_test_author_phone'
    assert person.home_street == u'_test_home_street'
    assert person.home_neighborhood == u'_test_home_neighborhood'
    assert person.home_city == u'_test_home_city'
    assert person.home_state == u'_test_home_state'
    assert person.home_zip == u'_test_home_zip'
    assert person.home_country == u'US'
    assert person.person_record_id == u'test.google.com/person.21009'
    assert person.photo_url == u'_test_photo_url'
    assert person.source_name == u'_test_source_name'
    assert person.source_url == u'_test_source_url'
    assert person.source_date == datetime.datetime(2000, 1, 1, 0, 0, 0)
    # Current date should replace the provided entry_date.
    assert person.entry_date.year == datetime.datetime.now().year

    notes = Note.get_by_person_record_id(person.person_record_id)
    assert len(notes) == 2
    notes.sort(key=lambda note: note.note_record_id)

    note = notes[0]
    assert note.author_name == u'_test_author_name'
    assert note.author_email == u'_test_author_email'
    assert note.author_phone == u'_test_author_phone'
    assert note.email_of_found_person == u'_test_email_of_found_person'
    assert note.phone_of_found_person == u'_test_phone_of_found_person'
    assert note.last_known_location == u'_test_last_known_location'
    assert note.note_record_id == u'test.google.com/note.27009'
    assert note.person_record_id == u'test.google.com/person.21009'
    assert note.text == u'_test_text'
    assert note.source_date == None
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert note.found
    assert note.status == u'believed_alive'
    assert note.linked_person_record_id == u'test.google.com/person.999'

    note = notes[1]
    assert note.author_name == u'inna-testing'
    assert note.author_email == u'inna-testing@gmail.com'
    assert note.author_phone == u'inna-testing-number'
    assert note.email_of_found_person == u''
    assert note.phone_of_found_person == u''
    assert note.last_known_location == u'19.16592425362802 -71.9384765625'
    assert note.note_record_id == u'test.google.com/note.31095'
    assert note.person_record_id == u'test.google.com/person.21009'
    assert note.text == u'new comment - testing'
    assert note.source_date == datetime.datetime(2010, 1, 17, 11, 13, 17)
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert not note.found
    assert not note.status
    assert not note.linked_person_record_id

  def test_api_write_pfif_1_2_note(self):
    """Post a single note-only entry as PFIF 1.2 using the upload API."""
    # Create person records that the notes will attach to.
    Person(key_name='test.google.com/person.21009',
           first_name='_test_first_name_1',
           last_name='_test_last_name_1',
           entry_date=datetime.datetime(2001, 1, 1, 1, 1, 1)).put()
    Person(key_name='test.google.com/person.21010',
           first_name='_test_first_name_2',
           last_name='_test_last_name_2',
           entry_date=datetime.datetime(2002, 2, 2, 2, 2, 2)).put()

    data = get_test_data('test.pfif-1.2-note.xml')
    self.s.go('http://%s/api/write?key=test_key' % self.hostport, data=data,
              type='application/xml')

    person = Person.get_by_key_name('test.google.com/person.21009')
    assert person
    notes = Note.get_by_person_record_id(person.person_record_id)
    assert len(notes) == 1
    note = notes[0]
    assert note.author_name == u'_test_author_name'
    assert note.author_email == u'_test_author_email'
    assert note.author_phone == u'_test_author_phone'
    assert note.email_of_found_person == u'_test_email_of_found_person'
    assert note.phone_of_found_person == u'_test_phone_of_found_person'
    assert note.last_known_location == u'_test_last_known_location'
    assert note.note_record_id == u'test.google.com/note.27009'
    assert note.person_record_id == u'test.google.com/person.21009'
    assert note.text == u'_test_text'
    assert note.source_date == None
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert note.found
    assert note.status == u'believed_alive'
    assert note.linked_person_record_id == u'test.google.com/person.999'

    person = Person.get_by_key_name('test.google.com/person.21010')
    assert person
    notes = Note.get_by_person_record_id(person.person_record_id)
    assert len(notes) == 1
    note = notes[0]
    assert note.author_name == u'inna-testing'
    assert note.author_email == u'inna-testing@gmail.com'
    assert note.author_phone == u'inna-testing-number'
    assert note.email_of_found_person == u''
    assert note.phone_of_found_person == u''
    assert note.last_known_location == u'19.16592425362802 -71.9384765625'
    assert note.note_record_id == u'test.google.com/note.31095'
    assert note.person_record_id == u'test.google.com/person.21010'
    assert note.text == u'new comment - testing'
    assert note.source_date == datetime.datetime(2010, 1, 17, 11, 13, 17)
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert not note.found
    assert not note.status
    assert not note.linked_person_record_id

  def test_api_write_pfif_1_1(self):
    """Post a single entry as PFIF 1.1 using the upload API."""
    data = get_test_data('test.pfif-1.1.xml')
    self.s.go('http://%s/api/write?key=test_key' % self.hostport, data=data,
              type='application/xml')
    person = Person.get_by_key_name('test.google.com/person.21009')
    assert person.first_name == u'_test_first_name'
    assert person.last_name == u'_test_last_name'
    assert person.author_name == u'_test_author_name'
    assert person.author_email == u'_test_author_email'
    assert person.author_phone == u'_test_author_phone'
    assert person.home_city == u'_test_home_city'
    assert person.home_street == u'_test_home_street'
    assert person.home_neighborhood == u'_test_home_neighborhood'
    assert person.home_state == u'_test_home_state'
    assert person.home_zip == u'_test_home_zip'
    assert person.person_record_id == u'test.google.com/person.21009'
    assert person.photo_url == u'_test_photo_url'
    assert person.source_name == u'_test_source_name'
    assert person.source_url == u'_test_source_url'
    assert person.source_date == datetime.datetime(2000, 1, 1, 0, 0, 0)
    # Current date should replace the provided entry_date.
    assert person.entry_date.year == datetime.datetime.now().year

    notes = Note.get_by_person_record_id(person.person_record_id)
    assert len(notes) == 2
    notes.sort(key=lambda note: note.note_record_id)

    note = notes[0]
    assert note.author_name == u'_test_author_name'
    assert note.author_email == u'_test_author_email'
    assert note.author_phone == u'_test_author_phone'
    assert note.email_of_found_person == u'_test_email_of_found_person'
    assert note.phone_of_found_person == u'_test_phone_of_found_person'
    assert note.last_known_location == u'_test_last_known_location'
    assert note.note_record_id == u'test.google.com/note.27009'
    assert note.text == u'_test_text'
    assert note.source_date == None
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert note.found

    note = notes[1]
    assert note.author_name == u'inna-testing'
    assert note.author_email == u'inna-testing@gmail.com'
    assert note.author_phone == u'inna-testing-number'
    assert note.email_of_found_person == u''
    assert note.phone_of_found_person == u''
    assert note.last_known_location == u'19.16592425362802 -71.9384765625'
    assert note.note_record_id == u'test.google.com/note.31095'
    assert note.text == u'new comment - testing'
    assert note.source_date == datetime.datetime(2010, 1, 17, 11, 13, 17)
    # Current date should replace the provided entry_date.
    assert note.entry_date.year == datetime.datetime.now().year
    assert not note.found

  def test_api_write_bad_key(self):
    """Attempt to post an entry with an invalid API key."""
    data = get_test_data('test.pfif-1.2.xml')
    self.s.go('http://%s/api/write?key=bad_key' % self.hostport, data=data,
              type='application/xml')
    assert self.s.status == 403

  def test_api_write_missing_field(self):
    """Attempt to post an entry with a missing required field."""
    data = get_test_data('test.pfif-1.2.xml')
    data = data.replace('_test_first_name', '  \n  ')
    doc = self.s.go('http://%s/api/write?key=test_key' % self.hostport,
                    data=data, type='application/xml')

    # The Person record should have been rejected.
    person_status = doc.first('status:write')
    assert person_status.first('status:written').text == '0'
    assert ('first_name is required'
            in person_status.first('status:error').text)

  def test_api_write_wrong_domain(self):
    """Attempt to post an entry with a domain that doesn't match the key."""
    data = get_test_data('test.pfif-1.2.xml')
    doc = self.s.go('http://%s/api/write?key=other_key' % self.hostport,
                    data=data,
                    type='application/xml')

    # The Person record should have been rejected.
    person_status = doc.first('status:write')
    assert person_status.first('status:written').text == '0'
    assert ('Not in authorized domain'
            in person_status.first('status:error').text)

    # Both of the Note records should have been rejected.
    note_status = person_status.next('status:write')
    assert note_status.first('status:written').text == '0'
    first_error = note_status.first('status:error')
    second_error = first_error.next('status:error')
    assert 'Not in authorized domain' in first_error.text
    assert 'Not in authorized domain' in second_error.text

  def test_api_read(self):
    """Fetch a single record as PFIF (1.1 and 1.2) using the read API."""
    db.put(Person(
        key_name='test.google.com/person.123',
        entry_date=datetime.datetime.now(),
        author_email='_read_author_email',
        author_name='_read_author_name',
        author_phone='_read_author_phone',
        first_name='_read_first_name',
        last_name='_read_last_name',
        sex='female',
        date_of_birth='1970-01-01',
        age='40-50',
        home_city='_read_home_city',
        home_neighborhood='_read_home_neighborhood',
        home_state='_read_home_state',
        home_street='_read_home_street',
        home_zip='_read_home_zip',
        home_country='_read_home_country',
        other='_read_other & < > "',
        photo_url='_read_photo_url',
        source_name='_read_source_name',
        source_url='_read_source_url',
        source_date=datetime.datetime(2001, 2, 3, 4, 5, 6),
    ))
    db.put(Note(
        key_name='test.google.com/note.456',
        author_email='_read_author_email',
        author_name='_read_author_name',
        author_phone='_read_author_phone',
        email_of_found_person='_read_email_of_found_person',
        last_known_location='_read_last_known_location',
        person_record_id='test.google.com/person.123',
        linked_person_record_id='test.google.com/person.888',
        phone_of_found_person='_read_phone_of_found_person',
        text='_read_text',
        source_date=datetime.datetime(2005, 5, 5, 5, 5, 5),
        entry_date=datetime.datetime(2006, 6, 6, 6, 6, 6),
        found=True,
        status='believed_missing'
    ))

    # Fetch a PFIF 1.1 document.
    # Note that author_email, author_phone, email_of_found_person, and
    # phone_of_found_person are omitted intentionally (see
    # utils.filter_sensitive_fields).
    doc = self.s.go(
        'http://%s/api/read?id=test.google.com/person.123' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<pfif:pfif xmlns:pfif="http://zesty.ca/pfif/1.1">
  <pfif:person>
    <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
    <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
    <pfif:author_name>_read_author_name</pfif:author_name>
    <pfif:source_name>_read_source_name</pfif:source_name>
    <pfif:source_date>2001-02-03T04:05:06Z</pfif:source_date>
    <pfif:source_url>_read_source_url</pfif:source_url>
    <pfif:first_name>_read_first_name</pfif:first_name>
    <pfif:last_name>_read_last_name</pfif:last_name>
    <pfif:home_city>_read_home_city</pfif:home_city>
    <pfif:home_state>_read_home_state</pfif:home_state>
    <pfif:home_neighborhood>_read_home_neighborhood</pfif:home_neighborhood>
    <pfif:home_street>_read_home_street</pfif:home_street>
    <pfif:home_zip>_read_home_zip</pfif:home_zip>
    <pfif:photo_url>_read_photo_url</pfif:photo_url>
    <pfif:other>_read_other &amp; &lt; &gt; "</pfif:other>
    <pfif:note>
      <pfif:note_record_id>test.google.com/note.456</pfif:note_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>_read_author_name</pfif:author_name>
      <pfif:source_date>2005-05-05T05:05:05Z</pfif:source_date>
      <pfif:found>true</pfif:found>
      <pfif:last_known_location>_read_last_known_location</pfif:last_known_location>
      <pfif:text>_read_text</pfif:text>
    </pfif:note>
  </pfif:person>
</pfif:pfif>
''', doc.content)

    # Fetch a PFIF 1.2 document.
    # Note that date_of_birth, author_email, author_phone,
    # email_of_found_person, and phone_of_found_person are omitted
    # intentionally (see utils.filter_sensitive_fields).
    doc = self.s.go(
        'http://%s/api/read?id=test.google.com/person.123&version=1.2' %
        self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<pfif:pfif xmlns:pfif="http://zesty.ca/pfif/1.2">
  <pfif:person>
    <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
    <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
    <pfif:author_name>_read_author_name</pfif:author_name>
    <pfif:source_name>_read_source_name</pfif:source_name>
    <pfif:source_date>2001-02-03T04:05:06Z</pfif:source_date>
    <pfif:source_url>_read_source_url</pfif:source_url>
    <pfif:first_name>_read_first_name</pfif:first_name>
    <pfif:last_name>_read_last_name</pfif:last_name>
    <pfif:sex>female</pfif:sex>
    <pfif:age>40-50</pfif:age>
    <pfif:home_street>_read_home_street</pfif:home_street>
    <pfif:home_neighborhood>_read_home_neighborhood</pfif:home_neighborhood>
    <pfif:home_city>_read_home_city</pfif:home_city>
    <pfif:home_state>_read_home_state</pfif:home_state>
    <pfif:home_postal_code>_read_home_zip</pfif:home_postal_code>
    <pfif:home_country>_read_home_country</pfif:home_country>
    <pfif:photo_url>_read_photo_url</pfif:photo_url>
    <pfif:other>_read_other &amp; &lt; &gt; "</pfif:other>
    <pfif:note>
      <pfif:note_record_id>test.google.com/note.456</pfif:note_record_id>
      <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
      <pfif:linked_person_record_id>test.google.com/person.888</pfif:linked_person_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>_read_author_name</pfif:author_name>
      <pfif:source_date>2005-05-05T05:05:05Z</pfif:source_date>
      <pfif:found>true</pfif:found>
      <pfif:status>believed_missing</pfif:status>
      <pfif:last_known_location>_read_last_known_location</pfif:last_known_location>
      <pfif:text>_read_text</pfif:text>
    </pfif:note>
  </pfif:person>
</pfif:pfif>
''', doc.content)

  def test_api_read_with_non_ascii(self):
    """Fetch a record containing non-ASCII characters using the read API.
    This tests both PFIF 1.1 and 1.2."""
    db.put(Person(
        key_name='test.google.com/person.123',
        entry_date=datetime.datetime.now(),
        author_name=u'a with acute = \u00e1',
        source_name=u'c with cedilla = \u00e7',
        source_url=u'e with acute = \u00e9',
        first_name=u'greek alpha = \u03b1',
        last_name=u'hebrew alef = \u05d0'
    ))

    # Fetch a PFIF 1.1 document.
    doc = self.s.go(
        'http://%s/api/read?id=test.google.com/person.123' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<pfif:pfif xmlns:pfif="http://zesty.ca/pfif/1.1">
  <pfif:person>
    <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
    <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
    <pfif:author_name>a with acute = \xc3\xa1</pfif:author_name>
    <pfif:source_name>c with cedilla = \xc3\xa7</pfif:source_name>
    <pfif:source_url>e with acute = \xc3\xa9</pfif:source_url>
    <pfif:first_name>greek alpha = \xce\xb1</pfif:first_name>
    <pfif:last_name>hebrew alef = \xd7\x90</pfif:last_name>
  </pfif:person>
</pfif:pfif>
''', doc.content)

    # Fetch a PFIF 1.2 document.
    doc = self.s.go(
        'http://%s/api/read?id=test.google.com/person.123&version=1.2' %
        self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<pfif:pfif xmlns:pfif="http://zesty.ca/pfif/1.2">
  <pfif:person>
    <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
    <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
    <pfif:author_name>a with acute = \xc3\xa1</pfif:author_name>
    <pfif:source_name>c with cedilla = \xc3\xa7</pfif:source_name>
    <pfif:source_url>e with acute = \xc3\xa9</pfif:source_url>
    <pfif:first_name>greek alpha = \xce\xb1</pfif:first_name>
    <pfif:last_name>hebrew alef = \xd7\x90</pfif:last_name>
  </pfif:person>
</pfif:pfif>
''', doc.content)

  def test_person_feed(self):
    """Fetch a single person using the PFIF Atom feed."""
    db.put(Person(
        key_name='test.google.com/person.123',
        entry_date=datetime.datetime.now(),
        author_email='_feed_author_email',
        author_name='_feed_author_name',
        author_phone='_feed_author_phone',
        first_name='_feed_first_name',
        last_name='_feed_last_name',
        sex='male',
        date_of_birth='1975',
        age='30-40',
        home_street='_feed_home_street',
        home_neighborhood='_feed_home_neighborhood',
        home_city='_feed_home_city',
        home_state='_feed_home_state',
        home_zip='_feed_home_zip',
        home_country='_feed_home_country',
        other='_feed_other & < > "',
        photo_url='_feed_photo_url',
        source_name='_feed_source_name',
        source_url='_feed_source_url',
        source_date=datetime.datetime(2001, 2, 3, 4, 5, 6),
    ))
    db.put(Note(
        key_name='test.google.com/note.456',
        author_email='_feed_author_email',
        author_name='_feed_author_name',
        author_phone='_feed_author_phone',
        email_of_found_person='_feed_email_of_found_person',
        last_known_location='_feed_last_known_location',
        person_record_id='test.google.com/person.123',
        linked_person_record_id='test.google.com/person.888',
        phone_of_found_person='_feed_phone_of_found_person',
        text='_feed_text',
        source_date=datetime.datetime(2005, 5, 5, 5, 5, 5),
        entry_date=datetime.datetime(2006, 6, 6, 6, 6, 6),
        found=True,
        status='is_note_author'
    ))

    # Feeds use PFIF 1.2.
    # Note that date_of_birth, author_email, author_phone,
    # email_of_found_person, and phone_of_found_person are omitted
    # intentionally (see utils.filter_sensitive_fields).
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:pfif="http://zesty.ca/pfif/1.2">
  <id>http://%s/feeds/person</id>
  <title>%s</title>
  <updated>....-..-..T..:..:..Z</updated>
  <link rel="self">http://%s/feeds/person</link>
  <entry>
    <pfif:person>
      <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>_feed_author_name</pfif:author_name>
      <pfif:source_name>_feed_source_name</pfif:source_name>
      <pfif:source_date>2001-02-03T04:05:06Z</pfif:source_date>
      <pfif:source_url>_feed_source_url</pfif:source_url>
      <pfif:first_name>_feed_first_name</pfif:first_name>
      <pfif:last_name>_feed_last_name</pfif:last_name>
      <pfif:sex>male</pfif:sex>
      <pfif:age>30-40</pfif:age>
      <pfif:home_street>_feed_home_street</pfif:home_street>
      <pfif:home_neighborhood>_feed_home_neighborhood</pfif:home_neighborhood>
      <pfif:home_city>_feed_home_city</pfif:home_city>
      <pfif:home_state>_feed_home_state</pfif:home_state>
      <pfif:home_postal_code>_feed_home_zip</pfif:home_postal_code>
      <pfif:home_country>_feed_home_country</pfif:home_country>
      <pfif:photo_url>_feed_photo_url</pfif:photo_url>
      <pfif:other>_feed_other &amp; &lt; &gt; "</pfif:other>
      <pfif:note>
        <pfif:note_record_id>test.google.com/note.456</pfif:note_record_id>
        <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
        <pfif:linked_person_record_id>test.google.com/person.888</pfif:linked_person_record_id>
        <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
        <pfif:author_name>_feed_author_name</pfif:author_name>
        <pfif:source_date>2005-05-05T05:05:05Z</pfif:source_date>
        <pfif:found>true</pfif:found>
        <pfif:status>is_note_author</pfif:status>
        <pfif:last_known_location>_feed_last_known_location</pfif:last_known_location>
        <pfif:text>_feed_text</pfif:text>
      </pfif:note>
    </pfif:person>
    <id>pfif:test.google.com/person.123</id>
    <title>_feed_first_name _feed_last_name</title>
    <author>
      <name>_feed_author_name</name>
    </author>
    <updated>2001-02-03T04:05:06Z</updated>
    <source>
      <title>%s</title>
    </source>
    <content>_feed_first_name _feed_last_name</content>
  </entry>
</feed>
''' % (hostport, hostport, hostport, hostport), doc.content)

    # Test the omit_notes parameter.
    doc = self.s.go('http://%s/feeds/person?omit_notes=yes' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:pfif="http://zesty.ca/pfif/1.2">
  <id>http://%s/feeds/person\?omit_notes=yes</id>
  <title>%s</title>
  <updated>....-..-..T..:..:..Z</updated>
  <link rel="self">http://%s/feeds/person\?omit_notes=yes</link>
  <entry>
    <pfif:person>
      <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>_feed_author_name</pfif:author_name>
      <pfif:source_name>_feed_source_name</pfif:source_name>
      <pfif:source_date>2001-02-03T04:05:06Z</pfif:source_date>
      <pfif:source_url>_feed_source_url</pfif:source_url>
      <pfif:first_name>_feed_first_name</pfif:first_name>
      <pfif:last_name>_feed_last_name</pfif:last_name>
      <pfif:sex>male</pfif:sex>
      <pfif:age>30-40</pfif:age>
      <pfif:home_street>_feed_home_street</pfif:home_street>
      <pfif:home_neighborhood>_feed_home_neighborhood</pfif:home_neighborhood>
      <pfif:home_city>_feed_home_city</pfif:home_city>
      <pfif:home_state>_feed_home_state</pfif:home_state>
      <pfif:home_postal_code>_feed_home_zip</pfif:home_postal_code>
      <pfif:home_country>_feed_home_country</pfif:home_country>
      <pfif:photo_url>_feed_photo_url</pfif:photo_url>
      <pfif:other>_feed_other &amp; &lt; &gt; "</pfif:other>
    </pfif:person>
    <id>pfif:test.google.com/person.123</id>
    <title>_feed_first_name _feed_last_name</title>
    <author>
      <name>_feed_author_name</name>
    </author>
    <updated>2001-02-03T04:05:06Z</updated>
    <source>
      <title>%s</title>
    </source>
    <content>_feed_first_name _feed_last_name</content>
  </entry>
</feed>
''' % (hostport, hostport, hostport, hostport), doc.content)

  def test_note_feed(self):
    """Fetch a single note using the PFIF Atom feed."""
    db.put(Person(
        key_name='test.google.com/person.123',
        entry_date=datetime.datetime.now(),
        first_name='_feed_first_name',
        last_name='_feed_last_name',
    ))
    db.put(Note(
        key_name='test.google.com/note.456',
        person_record_id='test.google.com/person.123',
        linked_person_record_id='test.google.com/person.888',
        author_email='_feed_author_email',
        author_name='_feed_author_name',
        author_phone='_feed_author_phone',
        email_of_found_person='_feed_email_of_found_person',
        last_known_location='_feed_last_known_location',
        phone_of_found_person='_feed_phone_of_found_person',
        text='_feed_text',
        source_date=datetime.datetime(2005, 5, 5, 5, 5, 5),
        entry_date=datetime.datetime(2006, 6, 6, 6, 6, 6),
        found=True,
        status='believed_dead'
    ))

    # Feeds use PFIF 1.2.
    # Note that author_email, author_phone, email_of_found_person, and
    # phone_of_found_person are omitted intentionally (see
    # utils.filter_sensitive_fields).
    doc = self.s.go('http://%s/feeds/note' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:pfif="http://zesty.ca/pfif/1.2">
  <id>http://%s/feeds/note</id>
  <title>%s</title>
  <updated>....-..-..T..:..:..Z</updated>
  <link rel="self">http://%s/feeds/note</link>
  <entry>
    <pfif:note>
      <pfif:note_record_id>test.google.com/note.456</pfif:note_record_id>
      <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
      <pfif:linked_person_record_id>test.google.com/person.888</pfif:linked_person_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>_feed_author_name</pfif:author_name>
      <pfif:source_date>2005-05-05T05:05:05Z</pfif:source_date>
      <pfif:found>true</pfif:found>
      <pfif:status>believed_dead</pfif:status>
      <pfif:last_known_location>_feed_last_known_location</pfif:last_known_location>
      <pfif:text>_feed_text</pfif:text>
    </pfif:note>
    <id>pfif:test.google.com/note.456</id>
    <title>_feed_text</title>
    <author>
      <name>_feed_author_name</name>
    </author>
    <updated>2005-05-05T05:05:05Z</updated>
    <content>_feed_text</content>
  </entry>
</feed>
''' % (hostport, hostport, hostport), doc.content)

  def test_person_feed_with_non_ascii(self):
    """Fetch a person containing non-ASCII fields using the PFIF Atom feed."""
    db.put(Person(
        key_name='test.google.com/person.123',
        entry_date=datetime.datetime.now(),
        author_name=u'a with acute = \u00e1',
        source_name=u'c with cedilla = \u00e7',
        source_url=u'e with acute = \u00e9',
        first_name=u'greek alpha = \u03b1',
        last_name=u'hebrew alef = \u05d0',
        source_date=datetime.datetime(2001, 2, 3, 4, 5, 6)
    ))

    # Note that author_email, author_phone, email_of_found_person, and
    # phone_of_found_person are omitted intentionally (see
    # utils.filter_sensitive_fields).
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert re.match(r'''<\?xml version="1.0" encoding="UTF-8"\?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:pfif="http://zesty.ca/pfif/1.2">
  <id>http://%s/feeds/person</id>
  <title>%s</title>
  <updated>....-..-..T..:..:..Z</updated>
  <link rel="self">http://%s/feeds/person</link>
  <entry>
    <pfif:person>
      <pfif:person_record_id>test.google.com/person.123</pfif:person_record_id>
      <pfif:entry_date>....-..-..T..:..:..Z</pfif:entry_date>
      <pfif:author_name>a with acute = \xc3\xa1</pfif:author_name>
      <pfif:source_name>c with cedilla = \xc3\xa7</pfif:source_name>
      <pfif:source_date>2001-02-03T04:05:06Z</pfif:source_date>
      <pfif:source_url>e with acute = \xc3\xa9</pfif:source_url>
      <pfif:first_name>greek alpha = \xce\xb1</pfif:first_name>
      <pfif:last_name>hebrew alef = \xd7\x90</pfif:last_name>
    </pfif:person>
    <id>pfif:test.google.com/person.123</id>
    <title>greek alpha = \xce\xb1 hebrew alef = \xd7\x90</title>
    <author>
      <name>a with acute = \xc3\xa1</name>
    </author>
    <updated>2001-02-03T04:05:06Z</updated>
    <source>
      <title>%s</title>
    </source>
    <content>greek alpha = \xce\xb1 hebrew alef = \xd7\x90</content>
  </entry>
</feed>
''' % (hostport, hostport, hostport, hostport), doc.content)

  def test_person_feed_parameters(self):
    """Test the max_results, skip, and min_entry_date parameters."""
    entities = []
    for i in range(1, 21):  # Create 20 persons.
      entities.append(Person(
        key_name='test.google.com/person.%d' % i,
        entry_date=datetime.datetime(2000, 1, 1, i, i, i),
        first_name='first.%d' % i,
        last_name='last.%d' % i
    ))
    db.put(entities)

    def assert_ids(*ids):
      self.assertEqual(list(ids), map(int, re.findall(
          r'record_id>test.google.com/person.(\d+)', self.s.doc.content)))

    # Should get records in reverse chronological order by default.
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12, 11)

    # Fewer results.
    doc = self.s.go('http://%s/feeds/person?max_results=1' % self.hostport)
    assert_ids(20)
    doc = self.s.go('http://%s/feeds/person?max_results=9' % self.hostport)
    assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12)

    # More results.
    doc = self.s.go('http://%s/feeds/person?max_results=12' % self.hostport)
    assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9)

    # Skip some results.
    doc = self.s.go(
        'http://%s/feeds/person?skip=12&max_results=5' % self.hostport)
    assert_ids(8, 7, 6, 5, 4)

    # Should get records in forward chronological order with min_entry_date.
    doc = self.s.go('http://%s/feeds/person?min_entry_date=%s' %
                    (self.hostport, '2000-01-01T18:18:18Z'))
    assert_ids(18, 19, 20)

    doc = self.s.go('http://%s/feeds/person?min_entry_date=%s' %
                    (self.hostport, '2000-01-01T03:03:03Z'))
    assert_ids(3, 4, 5, 6, 7, 8, 9, 10, 11, 12)

    doc = self.s.go('http://%s/feeds/person?min_entry_date=%s' %
                    (self.hostport, '2000-01-01T03:03:04Z'))
    assert_ids(4, 5, 6, 7, 8, 9, 10, 11, 12, 13)

  def test_note_feed_parameters(self):
    """Test the max_results, skip, min_entry_date, and person_record_id
    parameters."""
    Note.entry_date.auto_now = False  # Allow us to set entry_date for testing.
    try:
      entities = []
      for i in range(1, 3):  # Create person.1 and person.2.
        entities.append(Person(
          key_name='test.google.com/person.%d' % i,
          entry_date=datetime.datetime(2000, 1, 1, i, i, i),
          first_name='first',
          last_name='last'
        ))
      for i in range(1, 6):  # Create notes 1-5 on person.1.
        entities.append(Note(
          key_name='test.google.com/note.%d' % i,
          person_record_id='test.google.com/person.1',
          entry_date=datetime.datetime(2000, 1, 1, i, i, i)
        ))
      for i in range(6, 18):  # Create notes 6-17 on person.2.
        entities.append(Note(
          key_name='test.google.com/note.%d' % i,
          person_record_id='test.google.com/person.2',
          entry_date=datetime.datetime(2000, 1, 1, i, i, i)
        ))
      for i in range(18, 21):  # Create notes 18-20 on person.1.
        entities.append(Note(
          key_name='test.google.com/note.%d' % i,
          person_record_id='test.google.com/person.1',
          entry_date=datetime.datetime(2000, 1, 1, i, i, i)
        ))
      db.put(entities)

      def assert_ids(*ids):
        self.assertEqual(list(ids), map(int, re.findall(
            r'record_id>test.google.com/note.(\d+)', self.s.doc.content)))

      # Should get records in reverse chronological order by default.
      doc = self.s.go('http://%s/feeds/note' % self.hostport)
      assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12, 11)

      # Fewer results.
      doc = self.s.go('http://%s/feeds/note?max_results=1' % self.hostport)
      assert_ids(20)
      doc = self.s.go('http://%s/feeds/note?max_results=9' % self.hostport)
      assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12)

      # More results.
      doc = self.s.go('http://%s/feeds/note?max_results=12' % self.hostport)
      assert_ids(20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9)

      # Skip some results.
      doc = self.s.go(
          'http://%s/feeds/note?skip=12&max_results=5' % self.hostport)
      assert_ids(8, 7, 6, 5, 4)

      # Should get records in forward chronological order with min_entry_date.
      doc = self.s.go('http://%s/feeds/note?min_entry_date=%s' %
                      (self.hostport, '2000-01-01T18:18:18Z'))
      assert_ids(18, 19, 20)

      doc = self.s.go('http://%s/feeds/note?min_entry_date=%s' %
                      (self.hostport, '2000-01-01T03:03:03Z'))
      assert_ids(3, 4, 5, 6, 7, 8, 9, 10, 11, 12)

      doc = self.s.go('http://%s/feeds/note?min_entry_date=%s' %
                      (self.hostport, '2000-01-01T03:03:04Z'))
      assert_ids(4, 5, 6, 7, 8, 9, 10, 11, 12, 13)

      # Filter by person_record_id.
      doc = self.s.go('http://%s/feeds/note?person_record_id=%s' %
                      (self.hostport, 'test.google.com/person.1'))
      assert_ids(20, 19, 18, 5, 4, 3, 2, 1)

      doc = self.s.go('http://%s/feeds/note?person_record_id=%s' %
                      (self.hostport, 'test.google.com/person.2'))
      assert_ids(17, 16, 15, 14, 13, 12, 11, 10, 9, 8)

      doc = self.s.go(
          'http://%s/feeds/note?person_record_id=%s&max_results=11' %
          (self.hostport, 'test.google.com/person.2'))
      assert_ids(17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7)

      doc = self.s.go(
          'http://%s/feeds/note?person_record_id=%s&min_entry_date=%s' %
          (self.hostport, 'test.google.com/person.1', '2000-01-01T03:03:03Z'))
      assert_ids(3, 4, 5, 18, 19, 20)

      doc = self.s.go(
          'http://%s/feeds/note?person_record_id=%s&min_entry_date=%s' %
          (self.hostport, 'test.google.com/person.1', '2000-01-01T03:03:04Z'))
      assert_ids(4, 5, 18, 19, 20)

      doc = self.s.go(
          'http://%s/feeds/note?person_record_id=%s&min_entry_date=%s' %
          (self.hostport, 'test.google.com/person.2', '2000-01-01T06:06:06Z'))
      assert_ids(6, 7, 8, 9, 10, 11, 12, 13, 14, 15)

    finally:
      Note.entry_date.auto_now = True  # Restore Note.entry_date to normal.

  def test_api_read_status(self):
    """Test the reading of the note status field at /api/read and /feeds."""
    # /api defaults to PFIF 1.1.  /feeds uses PFIF 1.2.

    # A missing status should not appear as a tag.
    db.put(Person(
      key_name='test.google.com/person.1001',
      entry_date=datetime.datetime.now(),
      first_name='_status_first_name',
      last_name='_status_last_name',
      author_name='_status_author_name'
    ))
    doc = self.s.go(
      'http://%s/api/read?id=test.google.com/person.1001&version=1.2' %
      self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/note' % self.hostport)
    assert '<pfif:status>' not in doc.content

    # An unspecified status should not appear as a tag.
    db.put(Note(
      key_name='test.google.com/note.2002',
      person_record_id='test.google.com/person.1001'
    ))
    doc = self.s.go(
      'http://%s/api/read?id=test.google.com/person.1001&version=1.2' %
      self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/note' % self.hostport)
    assert '<pfif:status>' not in doc.content

    # An empty status should not appear as a tag.
    db.put(Note(
      key_name='test.google.com/note.2002',
      person_record_id='test.google.com/person.1001',
      status=''
    ))
    doc = self.s.go(
      'http://%s/api/read?id=test.google.com/person.1001&version=1.2' %
      self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert '<pfif:status>' not in doc.content
    doc = self.s.go('http://%s/feeds/note' % self.hostport)
    assert '<pfif:status>' not in doc.content

    # When the status is specified, it should appear in the feed.
    db.put(Note(
      key_name='test.google.com/note.2002',
      person_record_id='test.google.com/person.1001',
      status='believed_alive'
    ))
    doc = self.s.go(
      'http://%s/api/read?id=test.google.com/person.1001&version=1.2' %
      self.hostport)
    assert '<pfif:status>believed_alive</pfif:status>' in doc.content
    doc = self.s.go('http://%s/feeds/person' % self.hostport)
    assert '<pfif:status>believed_alive</pfif:status>' in doc.content
    doc = self.s.go('http://%s/feeds/note' % self.hostport)
    assert '<pfif:status>believed_alive</pfif:status>' in doc.content

  def test_analytics_id(self):
    """Checks that the analytics_id Secret is used for analytics."""
    doc = self.s.go('http://%s/create' % self.hostport)
    assert 'getTracker(' not in doc.content

    db.put(Secret(key_name='analytics_id', secret='analytics_id_xyz'))

    doc = self.s.go('http://%s/create' % self.hostport)
    assert "getTracker('analytics_id_xyz')" in doc.content

  def test_maps_api_key(self):
    """Checks that maps don't appear unless there is a maps_api_key Secret."""
    db.put(Person(
      key_name='test.google.com/person.1001',
      entry_date=datetime.datetime.now(),
      first_name='_status_first_name',
      last_name='_status_last_name',
      author_name='_status_author_name'
    ))
    doc = self.s.go('http://%s/create?role=provide' % self.hostport)
    assert 'map_canvas' not in doc.content
    doc = self.s.go(
        'http://%s/view?id=test.google.com/person.1001' % self.hostport)
    assert 'map_canvas' not in doc.content
    assert 'id="map_' not in doc.content

    db.put(Secret(key_name='maps_api_key', secret='maps_api_key_xyz'))

    doc = self.s.go('http://%s/create?role=provide' % self.hostport)
    assert 'maps_api_key_xyz' in doc.content
    assert 'map_canvas' in doc.content
    doc = self.s.go(
        'http://%s/view?id=test.google.com/person.1001' % self.hostport)
    assert 'maps_api_key_xyz' in doc.content
    assert 'map_canvas' in doc.content
    assert 'id="map_' in doc.content


if __name__ == '__main__':
  host = 'localhost'
  port = 8081
  start_server = True
  verbose = 0

  if '--port' in sys.argv:
    index = sys.argv.index('--port')
    sys.argv.pop(index)
    port = int(sys.argv.pop(index))
  if '--host' in sys.argv:
    index = sys.argv.index('--host')
    sys.argv.pop(index)
    host = sys.argv.pop(index)
    start_server = False
  if '--verbose' in sys.argv:
    index = sys.argv.index('--verbose')
    sys.argv.pop(index)
    verbose = sys.argv.pop(index)

  hostport = '%s:%d' % (host, port)
  status = 0
  try:
    if start_server:
      # Start up a clean new appserver for testing.
      appserver = AppServerProcess(port)
      appserver.wait_readiness()
    remote_api.init('haiticrisis', hostport, 'test', 'test')
    ReadOnlyTests.hostport = ReadWriteTests.hostport = hostport
    ReadOnlyTests.verbose = ReadWriteTests.verbose = verbose

    # Reset the datastore for the first test.
    reset_data()
    try:
      unittest.main()  # You can select tests using command-line arguments.
    except SystemExit, e:
      # unittest.main() will call sys.exit() on error
      status = int(e.code)
      if status:
        print >>sys.stderr, "Unit tests failed, exiting."
  except NotRunningError:
    print >>sys.stderr, "Server did not start up correctly, exiting."
    status = 1
  except BaseException:
    print >>sys.stderr, "Exception while running tests:"
    traceback.print_exc()
    status = 1
  finally:
    if start_server:
      appserver.terminate(status)
    else:
      sys.exit(status)
