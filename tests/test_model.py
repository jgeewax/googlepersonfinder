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

"""Tests for model.py."""

from datetime import datetime
from google.appengine.ext import db
import unittest
import model


class ModelTests(unittest.TestCase):
  """Test the loose odds and ends."""

  def setUp(self):
    self.p1 = model.Person(
      first_name="John",
      last_name="Smith",
      home_street="Washington St.",
      home_city="Los Angeles",
      home_state="California",
      home_zip="11111",
      home_neighborhood="Good Neighborhood",
      author_name="Alice Smith",
      author_phone="111-111-1111",
      author_email="alice.smith@gmail.com",
      source_url="https://www.source.com",
      source_date=datetime(2010,1,1),
      source_name="Source Name",
      entry_date=datetime(2010,1,1),
      other="")
    self.p2 = model.Person(
      first_name="Tzvika",
      last_name="Hartman",
      home_street="Herzl St.",
      home_city="Tel Aviv",
      home_state="Israel",
      entry_date=datetime(2010,1,1),
      other="")
    self.key_p1 = db.put(self.p1)
    self.key_p2 = db.put(self.p2)

    self.n1_1 = model.Note(person_record_id = self.p1.person_record_id,
                           linked_person_record_id = self.p2.person_record_id,
                           found = True)
    self.n1_2 = model.Note(person_record_id = self.p1.person_record_id,
                           found = True)
    self.key_n1_1 = db.put(self.n1_1)
    self.key_n1_2 = db.put(self.n1_2)

  def test_person(self):
    self.assertEqual(self.p1.first_name, "John")
    self.assertEqual(self.p1.photo_url, "")
    self.assertEqual(self.p1.found, False)
    person = model.Person
    self.assertEqual(self.p1.is_clone(), False)
    self.assertEqual(person.get_by_person_record_id(self.p1.person_record_id).
                     person_record_id,
                     self.p1.person_record_id)
    self.assertEqual(person.get_by_person_record_id(self.p2.person_record_id).
                     person_record_id,
                     self.p2.person_record_id)
    self.assertNotEqual(person.get_by_person_record_id(
                        self.p1.person_record_id).person_record_id,
                        self.p2.person_record_id)

    # Testing prefix properties
    self.assertEqual(hasattr(self.p1, "first_name_n_"), True)
    self.assertEqual(hasattr(self.p1, "home_street_n1_"), True)
    self.assertEqual(hasattr(self.p1, "home_zip_n2_"), True)

    # Testing indexing properties
    self.assertEqual(self.p1._fields_to_index_properties,
                     ["first_name", "last_name"])
    self.assertEqual(self.p1._fields_to_index_by_prefix_properties,
                     ["first_name", "last_name"])

  def test_note(self):
    note = model.Note
    self.assertEqual(self.n1_1.is_clone(), False)
    self.assertEqual(
        note.get_by_person_record_id(self.p1.person_record_id)[0].
        note_record_id,
        self.n1_1.note_record_id)
    self.assertEqual(
        note.get_by_person_record_id(self.p1.person_record_id)[1].
        note_record_id,
        self.n1_2.note_record_id)
    self.assertEqual(self.p1.get_linked_persons()[0].person_record_id,
                     self.p2.person_record_id)
    self.assertEqual(self.p2.get_linked_persons(), [])
    self.assertEqual(
        note.get_by_note_record_id(self.n1_1.note_record_id).note_record_id,
        self.n1_1.note_record_id)
    self.assertEqual(
        note.get_by_note_record_id(self.n1_2.note_record_id).note_record_id,
        self.n1_2.note_record_id)

if __name__ == '__main__':
  unittest.main()
