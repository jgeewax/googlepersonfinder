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


class Main(Handler):
  def get(self):
    if self.render_from_cache(cache_time=600):
      return
    stats = Stats.get_latest()
    # Round the stats to nearest 100 so people don't worry that it doesn't
    # increment every time they add a record.
    stats.num_people = int(round(stats.num_people, -2))
    stats.num_notes = int(round(stats.num_notes, -2))
    # We apparently have to pass num_people and num_notes as separate args
    # because blocktrans can't deal with stats.num_people.  WTF?
    self.render('templates/main.html', cache_time=600, params=self.params,
                num_people=stats.num_people, num_notes=stats.num_notes)

if __name__ == '__main__':
  run([('/', Main)], debug=False)
