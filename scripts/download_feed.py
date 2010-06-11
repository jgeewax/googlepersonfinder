#!/usr/bin/python2.5
# Copyright 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unix command-line utility to download PFIF records from Atom feeds."""

__author__ = 'kpy@google.com (Ka-Ping Yee)'

import csv
import os
import sys
import time

# This script is in a scripts directory below the root project directory.
SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
APP_DIR = os.path.join(PROJECT_DIR, 'app')
# Make imports work for Python modules that are part of this app.
sys.path.append(APP_DIR)

import pfif
import urllib


# Parsers for both types of records.
class PersonParser:
  def parse_file(self, file):
    return pfif.parse_file(file)[0]

class NoteParser:
  def parse_file(self, file):
    return pfif.parse_file(file)[1]

parsers = {'person': PersonParser, 'note': NoteParser}


# Writers for both types of records.
class CsvWriter:
  def __init__(self, filename):
    self.file = open(filename, 'w')
    self.writer = csv.DictWriter(self.file, self.fields)
    self.writer.writerow(dict((name, name) for name in self.fields))
    print >>sys.stderr, 'Writing CSV to: %s' % filename

  def write(self, records):
    for record in records:
      self.writer.writerow(dict(
          (name, value.encode('utf-8'))
          for name, value in record.items()))
    self.file.flush()

  def close(self):
    self.file.close()


class PersonCsvWriter(CsvWriter):
  fields = pfif.PFIF_1_2.fields['person']


class NoteCsvWriter(CsvWriter):
  fields = pfif.PFIF_1_2.fields['note']


class XmlWriter:
  def __init__(self, filename):
    self.file = open(filename, 'w')
    self.file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    self.file.write('<pfif:pfif xmlns:pfif="%s">\n' % pfif.PFIF_1_2.ns)
    print >>sys.stderr, 'Writing PFIF 1.2 XML to: %s' % filename

  def write(self, records):
    for record in records:
      self.write_record(self.file, record, indent='  ')
    self.file.flush()

  def close(self):
    self.file.write('</pfif:pfif>\n')
    self.file.close()


class PersonXmlWriter(XmlWriter):
  write_record = pfif.PFIF_1_2.write_person


class NoteXmlWriter(XmlWriter):
  write_record = pfif.PFIF_1_2.write_note

writers = {
  'xml': {'person': PersonXmlWriter, 'note': NoteXmlWriter},
  'csv': {'person': PersonCsvWriter, 'note': NoteCsvWriter}
}


def download_batch(url, min_entry_date, skip, parser):
  """Fetches and parses one batch of records from an Atom feed."""
  query = urllib.urlencode({
    'min_entry_date': min_entry_date,
    'skip': skip,
    'max_results': 200
  })
  if '?' in url:
    url += '&' + query
  else:
    url += '?' + query
  for attempt in range(5):
    try:
      return parser.parse_file(urllib.urlopen(url))
    except:
      continue
  raise RuntimeError('Failed to fetch %r after 5 attempts' % url)

def download_all_since(url, min_entry_date, parser, writer):
  """Fetches and parses batches of records repeatedly until all records
  with an entry_date >= min_entry_date are retrieved."""
  start_time = time.time()
  print >>sys.stderr, '  entry_date >= %s:' % min_entry_date,
  records = download_batch(url, min_entry_date, 0, parser)
  total = 0
  while records:
    writer.write(records)
    total += len(records)
    speed = total/float(time.time() - start_time)
    print >>sys.stderr, 'fetched %d (total %d, %.1f rec/s)' % (
        len(records), total, speed)
    min_entry_date = max(r['entry_date'] for r in records)
    skip = len([r for r in records if r['entry_date'] == min_entry_date])
    print >>sys.stderr, '  entry_date >= %s:' % min_entry_date,
    records = download_batch(url, min_entry_date, skip, parser)
  print >>sys.stderr, 'done.'

def main():
  if (len(sys.argv) != 6 or
      sys.argv[1] not in ['person', 'note'] or
      sys.argv[4] not in ['xml', 'csv']):
    raise SystemExit('Usage: ' + sys.argv[0] + ' {person,note} <feed_url> ' +
                     '<min_entry_date> {xml,csv} <output_filename>')
  type, feed_url, min_entry_date, format, output_filename = sys.argv[1:]

  parser = parsers[type]()
  writer = writers[format][type](output_filename)

  print >>sys.stderr, 'Fetching %s records since %s:' % (type, min_entry_date)
  download_all_since(feed_url, min_entry_date, parser, writer)
  writer.close()

if __name__ == '__main__':
  main()
