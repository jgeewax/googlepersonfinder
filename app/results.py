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

from model import *
from utils import *
import logging
import prefix

MAX_RESULTS = 100


class Results(Handler):
  def search(self, criteria, new_search):
    if new_search:
      return indexing.search(Person, criteria, MAX_RESULTS)
    else:
      query = Person.all().order('entry_date')
      query = prefix.filter_prefix(query, **criteria)
      return list(prefix.get_prefix_matches(query, MAX_RESULTS, **criteria))

  def reject_query(self, criteria):
    return self.redirect(
        '/query', role=self.params.role, small=self.params.small, style=self.params.style,
        error='error', **criteria)

  def get(self):
    new_search = self.request.get('new_search')
    # Gather the search criteria.
    criteria = {
      'first_name': self.params.first_name,
      'last_name': self.params.last_name,
      'home_city': self.params.home_city,
    }
    if self.params.role == 'provide':
      # Ensure that required parameters are present.
      if not (self.params.first_name and self.params.last_name):
        return self.reject_query(criteria)

      # Look for *similar* names, not prefix matches.
      for key in criteria:
        criteria[key] = criteria[key][:3]  # "similar" = same first 3 letters
      results = self.search(criteria, new_search)

      if results:
        # Perhaps the person you wanted to report has already been reported?
        return self.render('templates/results.html', params=self.params,
                           results=results, num_results=len(results))
      else:
        if self.params.small:
          # show a link to a create page.
          return self.render('templates/small-create.html', params=self.params)
        else:
          # No matches; proceed to create a new record.
          logging.info(repr(self.params.__dict__))
          return self.redirect('create', **self.params.__dict__)

    if self.params.role == 'seek':
      # Ensure that required parameters are present.
      if max(len(self.params.first_name), len(self.params.last_name)) < 2:
        return self.reject_query(criteria)

      # Look for prefix matches.
      results = self.search(criteria, new_search)

      # Show the (possibly empty) matches.
      return self.render('templates/results.html', params=self.params,
                         results=results, num_results=len(results))

if __name__ == '__main__':
  run([('/results', Results)], debug=False)
