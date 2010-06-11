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

"""The Person Finder data model, based on PFIF (http://zesty.ca/pfif)."""

__author__  = 'kpy@google.com (Ka-Ping Yee) and many other Googlers'

import datetime

from google.appengine.api import memcache
from google.appengine.ext import db
import indexing
import pfif
import prefix

# The domain of this repository.  Records created on this site ("original
# records") will have record_ids beginning with this domain and a slash.
HOME_DOMAIN = 'google.com'


# ==== PFIF record IDs =====================================================
# In App Engine, entity keys can have numeric ids or string names.  We use
# numeric ids for original records (so we can autogenerate unique ids), and
# string names for clone records (so we can handle external identifiers).
# Here are a few examples, assuming that HOME_DOMAIN is 'example.com':
#   - For an original record (created at this repository):
#         person_record_id: 'example.com/person.123'
#         entity key: db.Key.from_path('Person', 123)
#   - For a clone record (imported from an external repository):
#         person_record_id: 'other.domain.com/3bx7sQz'
#         entity key: db.Key.from_path('Person', 'other.domain.com/3bx7sQz')

def is_original(record_id):
  """Returns True if this is a record_id for an original record."""
  try:
    domain, local_id = record_id.split('/', 1)
    return domain == HOME_DOMAIN
  except ValueError:
    raise ValueError('%r is not a valid record_id' % record_id)

def key_from_record_id(record_id, expected_kind):
  """Returns the datastore Key corresponding to a PFIF record_id."""
  try:
    domain, local_id = record_id.split('/', 1)
    if domain == HOME_DOMAIN:  # original record
      type, id = local_id.split('.')
      kind, id = type.capitalize(), int(id)
      assert kind == expected_kind, 'not a %s: %r' % (expected_kind, record_id)
      return db.Key.from_path(kind, int(id))
    else:  # clone record
      return db.Key.from_path(expected_kind, record_id)
  except ValueError:
    raise ValueError('%r is not a valid record_id' % record_id)

def record_id_from_key(key):
  """Returns the PFIF record_id corresponding to a datastore Key."""
  assert len(key.to_path()) == 2  # We store everything in top-level entities.
  if key.id():  # original record
    return '%s/%s.%d' % (HOME_DOMAIN, str(key.kind().lower()), key.id())
  else:  # clone record
    return key.name()


# ==== Model classes =======================================================

class Base:
  """Mix-in class for methods common to both Person and Note entities."""
  def is_original(self):
    """Returns True if this record was created in this repository."""
    return self.key().id() is not None

  def is_clone(self):
    """Returns True if this record was imported from another repository."""
    return not self.is_original()


# All fields are either required, or have a default value.  For property
# types with a false value, the default is the false value.  For types with
# no false value, the default is None.

class Person(db.Model, Base):
  """The datastore entity kind for storing a PFIF person record."""

  # The entry_date should update every time a record is created or re-imported.
  entry_date = db.DateTimeProperty(required=True)

  author_name = db.StringProperty(default='', multiline=True)
  author_email = db.StringProperty(default='')
  author_phone = db.StringProperty(default='')
  source_name = db.StringProperty(default='')
  source_date = db.DateTimeProperty()
  source_url = db.StringProperty(default='')

  first_name = db.StringProperty(required=True)
  last_name = db.StringProperty(required=True)
  sex = db.StringProperty(default='', choices=pfif.PERSON_SEX_VALUES)
  date_of_birth = db.StringProperty(default='')  # YYYY, YYYY-MM, or YYYY-MM-DD
  age = db.StringProperty(default='')  # NN or NN-MM
  home_street = db.StringProperty(default='')
  home_neighborhood = db.StringProperty(default='')
  home_city = db.StringProperty(default='')
  home_state = db.StringProperty(default='')
  home_zip = db.StringProperty(default='')
  home_country = db.StringProperty(default='')
  photo_url = db.StringProperty(default='')
  other = db.TextProperty(default='')

  # found==true iff there is a note with found==true
  found = db.BooleanProperty(default=False)

  # Set to now on every creation/update of person or note on person.
  # This is updates on Person page change, e.g.,
  # - new note
  # - HTML change of the page
  # - duplicate mark 
  last_update_date = db.DateTimeProperty()

  # I tried without it but (adding it in indexing.py
  # but it doesn't work, not sure why
  names_prefixes = db.StringListProperty()

  @property
  def person_record_id(self):
    """Returns the fully qualified PFIF identifier for this record."""
    return record_id_from_key(self.key())

  def get_linked_persons(self, note_limit=200):
    """Retrieves the Persons linked to this Person.

    Linked persons represent duplicate Person entries.
    """
    linked_persons = []
    for note in Note.get_by_person_record_id(
        self.person_record_id, limit=note_limit):
      try:
        person = Person.get_by_person_record_id(note.linked_person_record_id)
      except:
        continue
      linked_persons.append(person)
    return linked_persons

  @classmethod
  def get_by_person_record_id(cls, person_record_id):
    """Retrieves a Person by its fully qualified unique identifier."""
    return Person.get(key_from_record_id(person_record_id, 'Person'))

  def update_index(self, which_indexing):
    #setup new indexing
    if 'new' in which_indexing:
      indexing.update_index_properties(self)
    # setup old indexing
    if 'old' in which_indexing:
      prefix.update_prefix_properties(self)


#new inedxing
indexing.add_fields_to_index_by_prefix_properties(Person,
                                                  'first_name', 'last_name');
indexing.add_fields_to_index_properties(Person,
                                        'first_name', 'last_name');
#old indexing
prefix.add_prefix_properties(
    Person, 'first_name', 'last_name', 'home_street', 'home_neighborhood',
    'home_city', 'home_state', 'home_zip')


class Note(db.Model, Base):
  """The datastore entity kind for storing a PFIF note record."""

  # The entry_date should update every time a record is re-imported.
  entry_date = db.DateTimeProperty(auto_now=True)

  person_record_id = db.StringProperty(required=True)

  # Use this field to store the person_record_id of a duplicate Person entry.
  linked_person_record_id = db.StringProperty(default='')

  author_name = db.StringProperty(default='', multiline=True)
  author_email = db.StringProperty(default='')
  author_phone = db.StringProperty(default='')
  source_date = db.DateTimeProperty()

  status = db.StringProperty(default='', choices=pfif.NOTE_STATUS_VALUES)
  found = db.BooleanProperty()
  email_of_found_person = db.StringProperty(default='')
  phone_of_found_person = db.StringProperty(default='')
  last_known_location = db.StringProperty(default='')
  text = db.TextProperty(default='')

  @property
  def note_record_id(self):
    """Returns the fully qualified unique identifier for this record."""
    return record_id_from_key(self.key())

  @classmethod
  def get_by_note_record_id(cls, note_record_id):
    """Retrieves a Note by its fully qualified PFIF identifier."""
    return Note.get(key_from_record_id(note_record_id, 'Note'))

  @classmethod
  def get_by_person_record_id(cls, person_record_id, limit=200):
    """Retreive notes for a person record, ordered by entry_date."""
    query = Note.all().filter('person_record_id =', person_record_id)
    return query.order('entry_date').fetch(limit)


class Photo(db.Model):
  """An entity kind for storing uploaded photos."""
  bin_data = db.BlobProperty()
  date = db.DateTimeProperty(auto_now_add=True)


class Authorization(db.Model):
  """Authorization tokens for the write API."""
  auth_key = db.StringProperty(required=True)
  domain = db.StringProperty(required=True)

  # Bookkeeping information for humans, not used programmatically.
  contact_name = db.StringProperty()
  contact_email = db.StringProperty()
  organization_name = db.StringProperty()


class Secret(db.Model):
  """A place to store application-level secrets in the database."""
  secret = db.BlobProperty()


class Stats(db.Model):
  """Stores a snapshot of the DB stats."""
  time = db.DateTimeProperty(auto_now_add=True)
  num_people = db.IntegerProperty(default=0)
  num_notes = db.IntegerProperty(default=0)

  @classmethod
  def get_latest(cls):
    stats = memcache.get('latest_stats')
    if stats:
      return stats
    recent_entries = db.Query(Stats).order('-time').fetch(10)
    if recent_entries:
      # The stats counter is unreliable and sometimes reports an incorrect
      # low number.  Work around this by using the max of the last few entries.
      stats = [max(recent_entries, key=lambda s: s.num_people)]
    if stats:
      # Cache the stats for 1 minute.  During this time after an update, users
      # will see either the old or new stats when they reload.  Keeping it
      # short makes it less erratic.
      memcache.set('latest_stats', stats[0], 60)
      return stats[0]
    return Stats()

  @classmethod
  def put_stats(cls, **kwargs):
    stats = cls(**kwargs)
    stats.put()


class SiteMapPingStatus(db.Model):
  """Tracks the last shard index that was pinged to the search engine"""
  search_engine = db.StringProperty(required=True)
  shard_index = db.IntegerProperty(default=-1)
