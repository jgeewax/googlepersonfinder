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

from datetime import datetime
from model import *
from utils import *
import prefix
import pfif
import reveal
import sys

# Fields to show for side-by-side comparison.
# Alas, we cannot use pfif.PFIF_1_2.fields exactly, because we store
# home_postal_code as home_zip in the datastore.
COMPARE_FIELDS = pfif.PFIF_1_2.fields['person'][:]  # Make a copy.
COMPARE_FIELDS[COMPARE_FIELDS.index('home_postal_code')] = 'home_zip'


class MultiView(Handler):
  def get(self):

    # To handle multiple persons,  We create a single object where each property
    # is a list of values, one for each person. This makes page rendering
    # easier.

    person = dict([(prop, []) for prop in COMPARE_FIELDS])
    any = dict([(prop, None) for prop in COMPARE_FIELDS])

    # Get all persons from db.
    # TODO: Can later optimize to use fewer DB calls.
    for num in range(1,10):
      id = self.request.get('id%d' % num)
      if not id:
        break
      p = Person.get_by_person_record_id(id)

      for prop in COMPARE_FIELDS:
        val = getattr(p, prop)
        person[prop].append(val)
        any[prop] = any[prop] or val

    # Check if private info should be revealed.
    content_id = 'multiview:' + ','.join(person['person_record_id'])
    reveal_url = reveal.make_reveal_url(self.request.url, content_id)
    show_private_info = reveal.verify(content_id, self.params.signature)

    # TODO: Handle no persons found.

    # Add a calculated full name property - used in the title.
    person['full_name'] = [fname + ' ' + lname for fname, lname in
        zip(person['first_name'], person['last_name']) ]
    standalone = self.request.get('standalone')

    # Note: we're not showing notes and linked persons information here at the
    # moment.
    self.render('templates/multiview.html', params=self.params,
                person=person, any=any, standalone=standalone,
                cols=len(person['first_name']) + 1,
                onload_function="view_page_loaded()", markdup=True,
                show_private_info=show_private_info, reveal_url=reveal_url)

  def post(self):
    if not self.params.text:
      return self.render('templates/error.html',
          message=_('Message is required. Please go back and try again.'))

    if not self.params.author_name:
      return self.render('templates/error.html',
          message=_('Your name is required in the "About you" section.  Please go back and try again.'))

    # TODO: To reduce possible abuse, we currently limit to 3 person
    # match. We could guard using e.g. an XSRF token, which I don't know how
    # to build in GAE.

    ids = set()
    for ind in range(1,4):
      id = getattr(self.params, 'id%d' % ind)
      if not id:
        break
      ids.add(id)

    if len(ids) > 1:
      notes = []
      for person_id in ids:
        for other_id in ids - set([person_id]):
          note = Note(
              person_record_id=person_id,
              linked_person_record_id=other_id,
              text=self.params.text,
              author_name=self.params.author_name,
              author_phone=self.params.author_phone,
              author_email=self.params.author_email,
              source_date=datetime.now())
          notes.append(note)
      db.put(notes)
    self.redirect('/view', id=self.params.id1)

if __name__ == '__main__':
  run([('/multiview', MultiView)], debug=False)
