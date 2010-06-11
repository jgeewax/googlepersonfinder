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

"""Support for approximate string prefix queries.

A hit is defined when the words entered in the query are all prefixes of one of
the words in the first and last names on the record
e.g.

a record with
first_name: ABC 123
last_name: DEF 456

will be retrieved by
"ABC 456"
"45 ED"
"123 ABC"
"ABC 123 DEF"

will not be retrieved by
"ABC 1234"
"ABC 123 DEF 456 789"
"""

from google.appengine.ext import db
import unicodedata
import logging

def words_to_index(string):
  """split the string on white space.
  In addition to the words we return the string it self
  TODO: do we want to split on non-alphabet chars (, or -)?"""
  words = string.split(None);
  if (len(words) > 10):
    logging.info("More than 10 words in name?! %s" % string)

  logging.debug("split '%s' to %d parts", string, len(words))

  return words;

def normalize_and_split(string):
  """Normalize a string to all uppercase, remove accents, delete apostrophes,
  and replace non-letters with spaces."""
  string = unicode(string or '').strip().upper()
  letters = []
  """TODO(eyalf): we need to have a better list of types we are keeping
    one that will work for non latin languages"""
  for ch in unicodedata.normalize('NFD', string):
    category = unicodedata.category(ch)
    if category.startswith('L'):
      letters.append(ch)
    elif category != 'Mn' and ch != "'":  # Treat O'Hearn as OHEARN
      letters.append(' ')
  return ''.join(letters).split()

def add_fields_to_index_properties(model_class, *properties):

  # Record the prefix properties.
  if not hasattr(model_class, '_fields_to_index_properties'):
    model_class._fields_to_index_properties = []
  model_class._fields_to_index_properties += list(properties)

  # adding the names_prefix property used for the index
  if not hasattr(model_class, 'names_prefixes'):
    model_class.names_prefixes = []

  # Update the model class.
  db._initialize_properties(
      model_class, model_class.__name__, model_class.__bases__,
      model_class.__dict__)


def add_fields_to_index_by_prefix_properties(model_class, *properties):

  # Record the prefix properties.
  if not hasattr(model_class, '_fields_to_index_by_prefix_properties'):
    model_class._fields_to_index_by_prefix_properties = []
  model_class._fields_to_index_by_prefix_properties += list(properties)

  # adding the names_prefix property used for the index
  if not hasattr(model_class, 'names_prefixes'):
    model_class.names_prefixes = []

  # Update the model class.
  db._initialize_properties(
      model_class, model_class.__name__, model_class.__bases__,
      model_class.__dict__)

def update_index_properties(entity):
  """Finds and updates all prefix-related properties on the given entity."""
  """Using the set to make sure I'm not adding the same string more than once"""
  names_prefixes = set()
  for property in entity._fields_to_index_properties:
    for value in normalize_and_split(getattr(entity, property)):
      if property in entity._fields_to_index_by_prefix_properties:
        for n in xrange(2,len(value)+1):
          pref = value[:n]
          if pref not in names_prefixes:
            names_prefixes.add(pref)
      else:
        if value not in names_prefixes:
          names_prefixes.add(value)

  """put a cap on the number of tokens just as a precaution """
  MAX_TOKENS = 100
  entity.names_prefixes = list(names_prefixes)[:MAX_TOKENS]
  if len(names_prefixes) > MAX_TOKENS:
    logging.debug('MAX_TOKENS exceeded for %s' %
                  (' '.join(list(names_prefixes))))

def search(model_class, criteria, max_results):
  query = model_class.all()
  query_words = []
  """TODO(eyalf): currently I'm assuming all criteria need to be splitted by
  to words which might be wrong in the future"""
  for property, query_string in criteria.items():
    query_words += normalize_and_split(query_string)

  logging.debug("query_words: %s" % query_words)
  if len(query_words) == 0:
    return [];
  for word in reversed(sorted(query_words, key=len)):
    query.filter('names_prefixes = ', word);

  res = query.fetch(max_results);
  logging.info('n results=%d' % len(res))
  return list(res)
