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

"""Exports the URLs of all person entries to a sitemap.xml file."""

__author__ = 'jocatalano@google.com (Joe Catalano) and many other Googlers'

import logging

from datetime import datetime
from datetime import timedelta
from google.appengine.api import urlfetch
from model import *
from time import *
from utils import *

_STATIC_SITEMAP_GENERATION_TIME = datetime(2010, 1, 24, 18, 0, 0)
# Note that we can only have 50000 shards since the static sitemap generation
# time, so for instance with 1.5 minute, this can only handle up to slightly
# less than 2 months.
_SHARD_SIZE_SECONDS = 90

def _create_person_query(filters, order):
  q = Person.all()
  for property_operator, value in filters:
    q.filter(property_operator, value)
  q.order(order)
  return q

def _compute_max_shard_index(now, sitemap_epoch):
  delta = now - sitemap_epoch
  delta_seconds = delta.days * 24 * 60 * 60 + delta.seconds
  return delta_seconds / _SHARD_SIZE_SECONDS

class SiteMap(Handler):
  _FETCH_LIMIT = 1000
  _FIELD = 'last_update_date'

  def get(self):
    requested_shard_index = self.request.get('shard_index')
    then = _STATIC_SITEMAP_GENERATION_TIME
    if not requested_shard_index:
      max_shard_index = _compute_max_shard_index(datetime.now(), then)
      shards = []
      for shard_index in range(max_shard_index + 1):
        shard = {}
        shard['index'] = shard_index
        shard['lastmod'] = format_sitemaps_datetime(
            then + timedelta(seconds=_SHARD_SIZE_SECONDS * (shard_index + 1)))
        shards.append(shard)
      self.render('templates/sitemap-index.xml', domain=self.domain,
                  static_lastmod=format_sitemaps_datetime(then), shards=shards)
    else:
      shard_index = int(requested_shard_index)
      assert 0 <= shard_index < 50000  #TODO: nicer error (400 maybe)
      persons = []
      time_lower = then + timedelta(seconds=_SHARD_SIZE_SECONDS * shard_index)
      time_upper = time_lower + timedelta(seconds=_SHARD_SIZE_SECONDS)
      q = _create_person_query(
          ((self._FIELD + ' >', time_lower), (self._FIELD + ' <=', time_upper)),
          self._FIELD)
      fetched_persons = q.fetch(self._FETCH_LIMIT)
      while fetched_persons:
        persons.extend(fetched_persons)
        q = _create_person_query(
            ((self._FIELD + ' >', getattr(fetched_persons[-1], self._FIELD)),
             (self._FIELD + ' <=', time_upper)),
            self._FIELD)
        fetched_persons = q.fetch(self._FETCH_LIMIT)
      urlinfos = [
          ({'person_record_id': p.person_record_id,
            'lastmod': format_sitemaps_datetime(getattr(p, self._FIELD))})
          for p in persons]
      domain = re.sub('[^.]*\.latest\.','',self.domain)
      self.render('templates/sitemap.xml', domain=domain, urlinfos=urlinfos)

class SiteMapPing(Handler):
  """Pings the index server with sitemap files that are new since last ping"""
  _INDEXER_MAP = {'google': 'http://www.google.com/webmasters/tools/ping?',
                  'not-specified': ''}

  def get(self):
    search_engine = self.request.get('search_engine')
    if not search_engine:
      search_engine = 'not-specified'

    last_update_query = SiteMapPingStatus.all()
    last_update_query.filter('search_engine = ', search_engine)
    last_update_status = last_update_query.fetch(1)
    if not last_update_status:
      last_shard = -1
      last_update_status = SiteMapPingStatus(search_engine=search_engine)
    else:
      last_update_status = last_update_status[0]
      last_shard = last_update_status.shard_index

    max_shard_index = _compute_max_shard_index(datetime.now(),
                                               _STATIC_SITEMAP_GENERATION_TIME)
    if not self.ping_indexer(last_shard+1, max_shard_index, search_engine,
                             last_update_status):
      self.error(500)

  def ping_indexer(self, start_index, end_index, search_engine, status):
    """Pings the server with sitemap updates and returns True if all succeed"""
    try:
      for shard_index in range(start_index, end_index + 1):
        ping_url = self._INDEXER_MAP[search_engine]
        sitemap_url = ('http://' + self.domain + '/sitemap?shard_index=' +
                       str(shard_index))
        ping_url = ping_url + urlencode({'sitemap': sitemap_url})
        response = urlfetch.fetch(url=ping_url, method=urlfetch.GET)
        if not response.status_code == 200:
          #TODO(jocatalano): Retry and/or email haiticrisis on failures.
          logging.error("Received " + response.status_code + " pinging " +
                        ping_url)
          return False
        else:
          status.shard_index = shard_index
      return True
    finally:
      # Always update database to reflect how many the max shard that was pinged
      # particularly when a DeadlineExceededError is thrown
      db.put(status)


if __name__ == '__main__':
  run([('/sitemap', SiteMap),('/sitemap/ping', SiteMapPing)], debug=False)
