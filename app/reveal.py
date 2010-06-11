#!/usr/bin/python2.4
#
# Copyright 2010 Google Inc. All Rights Reserved.

"""Handler for a Turing test page, and utility functions for other pages,
to guard the display of sensitive information."""

__author__ = 'kpy@google.com (Ka-Ping Yee)'

import cgi
import logging
import pickle
import random
import sha
import time
from google.appengine.api import users
from model import Secret
from utils import *


# ==== Key management ======================================================

def generate_random_key():
  """Generates a random 20-byte key."""
  return ''.join(chr(random.randrange(256)) for i in range(20))

def get_reveal_key():
  """Gets the secret key for authorizing reveal operations."""
  secret = Secret.get_by_key_name('reveal')
  if not secret:
    secret = Secret(key_name='reveal', secret=generate_random_key())
    secret.put()
  return secret.secret


# ==== Signature generation and verification ===============================

def sha1_hash(string):
  """Computes the SHA-1 hash of the given string."""
  return sha.new(string).digest()

def xor(string, byte):
  """Exclusive-ors each character in a string with the given byte."""
  results = []
  for ch in string:
    results.append(chr(ord(ch) ^ byte))
  return ''.join(results)

def hmac(key, data, hash=sha1_hash):
  """Produces an HMAC for the given data."""
  return hash(xor(key, 0x5c) + hash(xor(key, 0x36) + pickle.dumps(data)))

def sign(data, lifetime=600):
  """Produces a limited-time signature for the given data."""
  data = str(data)
  expiry = int(time.time() + lifetime)
  key = get_reveal_key()
  return hmac(key, (expiry, data)).encode('hex') + '.' + str(expiry)

def verify(data, signature):
  """Checks that a signature matches the given data and hasn't yet expired."""
  try:
    mac, expiry = signature.split('.', 1)
    mac, expiry = mac.decode('hex'), int(expiry)
  except (TypeError, ValueError):
    return False
  data = str(data)
  key = get_reveal_key()
  return time.time() < expiry and hmac(key, (expiry, data)) == mac

def make_reveal_url(target, content_id):
  """Produces a link to this reveal handler that, on success, redirects back
  to the given 'target' URL with a signature for the given 'content_id'."""
  return '/reveal?' + urllib.urlencode({
    'target': target,
    'content_id': content_id,
  })


# ==== The reveal page, which authorizes revelation ========================
# To use this facility, handlers that want to optionally show sensitive
# information should do the following:
#
# 1.  Construct a 'content_id' string that canonically identifies what is
#     being requested (e.g. the name of the page and any parameters that
#     control what is shown on the page).
#
# 2.  Call reveal.verify(content_id, self.params.signature) to find out
#     whether the sensitive information should be shown.
#
# 3.  If reveal.verify() returns False, then replace the sensitive information
#     with a link to make_reveal_url(self.request.url, content_id).

class Reveal(Handler):
  def get(self):
    # For now, signing in is sufficient to reveal information.
    # We could put a Turing test here instead.
    user = users.get_current_user()
    self.render('templates/reveal.html', user=user, params=self.params,
                login_url=users.create_login_url(self.request.url))

  def post(self):
    user = users.get_current_user()
    if user:
      logging.info('revealing %r to user %r' %
                   (self.params.content_id, user.email()))
      signature = sign(self.params.content_id)
      self.redirect(set_url_param(self.params.target, 'signature', signature))
    else:
      self.redirect('/reveal?' + urllib.urlencode({
        'target': self.params.target,
        'content_id': self.params.content_id
      }))

if __name__ == '__main__':
  run([('/reveal', Reveal)], debug=False)
