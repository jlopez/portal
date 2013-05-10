#!/usr/bin/env python
from functools import wraps

import cookielib
import HTMLParser
import json
import os
import sys
import re
import urllib
import urllib2
import urlparse
import uuid

def cached(wrapped):
    @wraps(wrapped)
    def wrapper():
        if not hasattr(wrapped, 'cache'):
            wrapped.cache = wrapped()
        return wrapped.cache
    return wrapper

def cached_method(wrapped):
    @wraps(wrapped)
    def wrapper(self):
        name = '%s_cache' % wrapped.__name__
        if not hasattr(self, name):
            setattr(self, name, wrapped(self))
        return getattr(self, name)
    return wrapper

def _ensure_parents_exist(filename):
    dirname = os.path.dirname(filename)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)
    assert not dirname or os.path.isdir(dirname), (
            "Path %s is not a directory" % dirname)

class APIException(Exception): pass

class APIServiceException(APIException):
    def __init__(self, info):
        if info['userString'] != info['resultString']:
            super(APIServiceException, self).__init__(
                    '%s (Error %s: %s)' % (info['userString'],
                        info['resultCode'], info['resultString']))
        else:
            super(APIServiceException, self).__init__(
                    '%s (Error %s)' % (info['userString'],
                        info['resultCode']))
        self.info = info
        self.code = info['resultCode']

class API(object):
    LOGIN_URL = 'https://developer.apple.com/account/login.action'
    DEVELOPER_URL = 'https://developer.apple.com'
    DEVELOPER_SERVICES_URL = '%s/services-developerportal/QH65B2/account/ios' % DEVELOPER_URL

    GET_TEAM_ID_URL = 'https://developer.apple.com/account/ios/certificate/certificateList.action'

    class _LoginHTMLParser(HTMLParser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "form":
                attrs = { k: v for k, v in attrs }
                if attrs['name'] == 'appleConnectForm':
                    self.url = attrs['action']

        def feed(self, data):
            try:
                HTMLParser.HTMLParser.feed(self, data)
            except HTMLParser.HTMLParseError:
                pass

    def __init__(self, debug=False):
        cookie_jar = cookielib.CookieJar()
        processor = urllib2.HTTPCookieProcessor(cookie_jar)
        self._opener = urllib2.build_opener(processor)
        self._debug = debug

    def login(self, user=None, password=None):
        if not user or not password:
            user, password = self._find_credentials()
        try:
            r = self._opener.open(self.LOGIN_URL)
            parser = self._LoginHTMLParser()
            page = r.read()
            parser.feed(page)
            if not parser.url:
                if self._debug:
                    print >>sys.stderr, "Page contents:\n%s" % page
                raise APIException("Login failed: unable to locate login URL (HTML scraping failure)")
            scheme, netloc, _, _, _, _ = urlparse.urlparse(r.geturl())
            url = '%s://%s%s' % (scheme, netloc, parser.url)
            params = dict(theAccountName=user, theAccountPW=password,
                          theAuxValue='')
            r = self._opener.open(url, urllib.urlencode(params))
            r = self._opener.open(self.GET_TEAM_ID_URL)
            page = r.read()
            matcher = re.search(r'teamId=([A-Z0-9]*)', page)
            if not matcher:
                if self._debug:
                    print >>sys.stderr, "Login failed, page contents:\n%s" % page
                raise APIException("Login failed, please check credentials (using %s)" % user)
            self._team_id = matcher.group(1)
        except urllib2.URLError as e:
            raise e

    def _api(self, cmd, form={}, **kwargs):
        try:
            if isinstance(form, (dict, list)):
                form = urllib.urlencode(form)
            kwargs['content-type'] = 'text/x-url-arguments'
            kwargs['accept'] = 'application/json'
            kwargs['requestId'] = str(uuid.uuid4())
            kwargs['userLocale'] = 'en_US'
            kwargs['teamId'] = self._team_id
            query = urllib.urlencode(kwargs)
            url = "%s/%s?%s" % (self.DEVELOPER_SERVICES_URL, cmd, query)
            response = self._opener.open(url, form)
            assert response.getcode() == 200, "Error %" % response.getcode()
            data = json.loads(response.read())
            rc = data['resultCode']
            if rc not in [ 0, 8500 ]:
                raise APIServiceException(data)
            return data
        except urllib2.URLError as e:
            raise e

    def _find_credentials(self):
        # First try environment variables
        try:
            credentials = os.environ['PORTAL_CREDENTIALS']
            user, password = credentials.split(':')
            return user, password
        except (KeyError, ValueError):
            pass

        # Now try .portalrc file
        def search_path():
            yield os.path.expanduser('~/.portalrc')
            path = os.getcwd()
            while True:
                filename = os.path.join(path, '.portalrc')
                if os.path.isfile(filename):
                    yield filename
                    break
                if path == '/':
                    break
                path = os.path.dirname(path)

        import ConfigParser
        try:
            cfg = ConfigParser.RawConfigParser()
            cfg.read(search_path())
            return cfg.get('Main', 'user'), cfg.get('Main', 'password')
        except ConfigParser.Error:
            raise APIException('Missing credentials (.portalrc / PORTAL_CREDENTIALS)')

    def _list_cert_requests(self):
        data = self._api("certificate/listCertRequests", certificateStatus=0,
            types=self.ALL_CERT_TYPES)
        return data['certRequests']

    def _list_app_ids(self):
        data = self._api('identifiers/listAppIds') #, onlyCountLists='true')
        return data['appIds']

    def _list_provisioning_profiles(self):
        data = self._api('profile/listProvisioningProfiles',
                includeInactiveProfiles='true', onlyCountLists='true')
        return data['provisioningProfiles']

    def _list_devices(self, include_removed=True):
        data = self._api('device/listDevices',
                includeRemovedDevices='true' if include_removed else 'false')
        return data['devices']

    @cached_method
    def all_cert_requests(self):
        return self._list_cert_requests()

    @cached_method
    def all_app_ids(self):
        return self._list_app_ids()

    @cached_method
    def all_provisioning_profiles(self):
        return self._list_provisioning_profiles()

    @cached_method
    def all_devices(self):
        return self._list_devices()

    def clear_cache(self):
        for n in self.__dict__:
            if n.endswith('_cache'):
                delattr(self, n)

    def list_cert_requests(self, typ):
        if not isinstance(typ, list):
            typ = [ typ ]
        return [ c for c in self.all_cert_requests()
                 if c['certificateTypeDisplayId'] in typ ]

    def update_provisioning_profile(self, profile, name=None, app_id=None,
            certificate_ids=None, device_ids=None, distribution_type=None):
        form = []
        form.append(('provisioningProfileId', profile['provisioningProfileId']))
        form.append(('distributionType', distribution_type or profile['distributionMethod']))
        form.append(('returnFullObjects', 'false'))
        form.append(('provisioningProfileName', name or profile['name']))
        form.append(('appIdId', app_id or profile['appId']['appIdId']))
        for certificate_id in certificate_ids or profile['certificateIds']:
            if isinstance(certificate_id, dict):
                certificate_id = certificate_id['certificateId']
            form.append(('certificateIds', certificate_id))
        if device_ids is None:
            device_ids = profile['deviceIds']
        for device_id in device_ids:
            if isinstance(device_id, dict):
                device_id = device_id['deviceId']
            form.append(('deviceIds', device_id))
        return self._api('profile/regenProvisioningProfile', form=form)

    def _make_dev_url(self, path, **kwargs):
        query = urllib.urlencode(kwargs)
        return "%s/%s.action?%s" % (self.DEVELOPER_URL, path, query)

    def download_profile(self, profile, file_or_filename):
        try:
            if isinstance(profile, dict):
                profile = profile['provisioningProfileId']
            url = self._make_dev_url('account/ios/profile/profileContentDownload',
                    displayId=profile)
            r = self._opener.open(url)
            assert r.getcode() == 200, 'Unable to download profile [%s]' % profile
            profile = r.read()
            if isinstance(file_or_filename, basestring):
                _ensure_parents_exist(file_or_filename)
                with open(file_or_filename, 'wb') as f:
                    f.write(profile)
            else:
                file_or_filename.write(profile)
        except urllib2.HTTPError as e:
            if e.getcode() == 404:
                raise APIException("Profile '%s' not found" % profile)
            raise e

    def profile_type(self, profile):
        if profile['type'] == 'Development':
            return 'development'
        return 'adhoc' if profile['deviceCount'] else 'appstore'

    def is_profile_expired(self, profile):
        return profile['status'] == 'Expired'

    ALL_CERT_TYPES = "5QPB9NHCEI,R58UK2EWSO,9RQEK7MSXA,LA30L5BJEU,BKLRAVXMGM,3BQKVH9I2X,Y3B2F3TYSI"
    (CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION,
     CERT_TYPE_UNKNOWN_1, CERT_TYPE_UNKNOWN_2,
     CERT_TYPE_APN_DEVELOPMENT, CERT_TYPE_APN_PRODUCTION,
     CERT_TYPE_UNKNOWN_3) = ALL_CERT_TYPES.split(',')
    CERT_TYPE_IOS = [ CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION ]
