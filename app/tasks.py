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

from utils import *
from model import *

def make_key_query(model_type):
  """Make a query on all the keys of a given kind, in ascending order."""
  return db.Query(model_type, keys_only=True).order('__key__')

def count_records(model_type):
  """Count the number of entities in the datastore of a given kind."""
  FETCH_LIMIT = 1000
  count = 0

  fetched_keys = make_key_query(model_type).fetch(FETCH_LIMIT)
  while fetched_keys:
    count += len(fetched_keys)
    logging.debug('%d so far, last: %s', count, str(fetched_keys[-1]))
    fetched_keys = make_key_query(model_type).filter(
        '__key__ >', fetched_keys[-1]).fetch(FETCH_LIMIT)
  return count

class UpdateStats(Handler):
  def get(self):
    num_people = count_records(Person)
    num_notes = count_records(Note)
    Stats.put_stats(num_people=num_people, num_notes=num_notes)

    msg = ('<table>' +
           '<tr><td>Person entities:<td>%d</tr>' % num_people +
           '<tr><td>Note entities<td>%d</tr>' % num_notes +
           '</table>')
    self.write(msg)


if __name__ == '__main__':
  run([('/tasks/update_stats', UpdateStats)], debug=True)
