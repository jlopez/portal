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
            self.team_id = matcher.group(1)
            self.user = user
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
            kwargs['teamId'] = self.team_id
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
        group = os.environ.get('PORTAL_ENVIRONMENT', 'Default')
        try:
            cfg = ConfigParser.RawConfigParser()
            cfg.read(search_path())
            return cfg.get(group, 'user'), cfg.get(group, 'password')
        except ConfigParser.Error:
            raise APIException('Missing credentials '
                '(.portalrc section [%s] / PORTAL_CREDENTIALS)' % group)

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

    def clear_cache(self):
        for n in self.__dict__:
            if n.endswith('_cache'):
                delattr(self, n)

    @cached_method
    def all_cert_requests(self):
        return self._list_cert_requests()

    def list_cert_requests(self, typ):
        if not isinstance(typ, list):
            typ = [ typ ]
        return [ c for c in self.all_cert_requests()
                 if c['certificateTypeDisplayId'] in typ ]

    @cached_method
    def all_app_ids(self):
        return self._list_app_ids()

    def get_app_id(self, app_id):
        if isinstance(app_id, (list, tuple)):
            return [ self.get_app_id(a) for a in app_id ]
        if isinstance(app_id, dict):
            return app_id
        if not isinstance(app_id, basestring):
            raise APIException('invalid app_id %s' % app_id)
        try:
            if '.' in app_id:
                return next(a for a in self.all_app_ids()
                            if a['identifier'] == app_id)
            else:
                return next(a for a in self.all_app_ids()
                            if a['appIdId'] == app_id)
        except StopIteration:
            return None

    @cached_method
    def all_devices(self):
        return self._list_devices()

    def get_device(self, device, return_id_if_missing=False):
        if isinstance(device, (list, tuple)):
            return [ self.get_device(d,
                     return_id_if_missing=return_id_if_missing)
                     for d in device ]
        if isinstance(device, dict):
            return device
        if not isinstance(device, basestring):
            raise APIException('invalid device %s' % device)
        try:
            if re.match('[0-9a-f]{40}', device, re.I):
                return next(d for d in self.all_devices()
                            if d['deviceNumber'] == device)
            else:
                return next(d for d in self.all_devices()
                            if d['deviceId'] == device)
        except StopIteration:
            if return_id_if_missing:
                return device
            return None

    def add_device(self, udid, name=None):
        name = name or udid
        form = []
        form.append(('register', 'single'))
        form.append(('name', name))
        form.append(('deviceNumber', udid))
        form.append(('deviceNames', name))
        form.append(('deviceNumbers', udid))
        data = self._api("device/addDevice", form=form)
        return data['device']

    def delete_device(self, device):
        if not isinstance(device, (basestring, dict)):
            raise APIException('invalid device %s' % device)
        device = self.get_device(device)
        self._api('device/deleteDevice',
                deviceId=device['deviceId'])

    def enable_device(self, device):
        if not isinstance(device, (basestring, dict)):
            raise APIException('invalid device %s' % device)
        device = self.get_device(device)
        data = self._api('device/enableDevice',
                displayId=device['deviceId'],
                deviceNumber=device['deviceNumber'])
        return data['device']

    @cached_method
    def all_provisioning_profiles(self):
        return self._list_provisioning_profiles()

    def get_provisioning_profile(self, profile, return_id_if_missing=False):
        if isinstance(profile, (list, tuple)):
            return [ self.get_provisioning_profile(p,
                         return_id_if_missing=return_id_if_missing)
                     for p in profile ]
        if isinstance(profile, dict):
            return profile
        if not isinstance(profile, basestring):
            raise APIException('invalid profile id %s' % profile)
        try:
            return next(p for p in self.all_provisioning_profiles()
                        if p['provisioningProfileId'] == profile)
        except StopIteration:
            if return_id_if_missing:
                return profile
            return None

    def create_provisioning_profile(self, profile_type, app_id, certificates=None,
            devices=None, name=None):
        if not 0 <= profile_type < 3:
            raise APIException('profile_type must be one of ' +
              ', '.join(t for t in dir(API) if t.startswith('PROFILE_TYPE_')))
        if not isinstance(app_id, (dict, basestring)):
            raise APIException('invalid app_id %s' % app_id)
        distribution_type = 'limited adhoc store'.split()[profile_type]
        if profile_type == self.PROFILE_TYPE_DEVELOPMENT:
            distribution_type_label = 'Distribution'
        else:
            distribution_type_label = 'Development'
        app_id = self.get_app_id(app_id)
        if certificates is None:
            if profile_type == API.PROFILE_TYPE_DEVELOPMENT:
                cert_type = API.CERT_TYPE_IOS_DEVELOPMENT
            else:
                cert_type = API.CERT_TYPE_IOS_DISTRIBUTION
            certificates = self.list_cert_requests(cert_type)
        certificates = self._unwrap(certificates, 'certificateId')
        devices = self._unwrap(devices or (), 'deviceId')
        if not name:
            name = '%s %s' % (app_id['name'],
                'Development AdHoc AppStore'.split()[profile_type])

        form = []
        form.append(('distributionType', distribution_type))
        form.append(('appIdId', app_id['appIdId']))
        form.append(('certificateIds', self._format_list(certificates)))
        for device in devices:
            form.append(('devices', device))
        if devices:
            form.append(('deviceIds', self._format_list(devices)))
        form.append(('template', ''))
        form.append(('returnFullObjects', 'false'))
        form.append(('provisioningProfileName', name))
        form.append(('distributionTypeLabel', distribution_type_label))
        form.append(('appIdName', app_id['name']))
        form.append(('appIdPrefix', app_id['prefix']))
        form.append(('appIdIdentifier', app_id['identifier']))
        form.append(('certificateCount', len(certificates)))
        form.append(('deviceCount', len(devices) if devices else ''))
        data = self._api("profile/createProvisioningProfile", form=form)
        return data['provisioningProfile']

    def delete_provisioning_profile(self, profile):
        profile = self._unwrap(profile, 'provisioningProfileId')
        self._api('profile/deleteProvisioningProfile',
            provisioningProfileId=profile)

    def _format_list(self, objs):
        if objs:
            return '[%s]' % ','.join(objs)
        return ''

    def _unwrap(self, obj, key):
        if obj is None:
            return obj
        if isinstance(obj, (list, tuple)):
            return [ self._unwrap(o, key) for o in obj ]
        if isinstance(obj, basestring):
            return obj
        return obj[key]

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
        if isinstance(profile, int):
            if not 0 <= profile < len(API._PROFILE_TYPE_LABELS):
                raise APIException('Invalid profile type %s' % profile)
            return profile
        if isinstance(profile, basestring):
            try:
                return self.profile_type(int(profile))
            except ValueError:
                pass
            try:
                return API._PROFILE_TYPE_LABELS.index(profile)
            except ValueError:
                raise APIException("Invalid profile type '%s'" % profile)
        if not isinstance(profile, dict):
            raise APIException('Invalid  profile %s' % profile)
        if profile['type'] == 'Development':
            return API.PROFILE_TYPE_DEVELOPMENT
        if profile['deviceCount']:
            return API.PROFILE_TYPE_ADHOC
        return API.PROFILE_TYPE_APPSTORE

    def profile_type_name(self, profile):
        return API._PROFILE_TYPE_LABELS[self.profile_type(profile)]

    def is_profile_expired(self, profile):
        return profile['status'] == 'Expired'

    PROFILE_TYPE_DEVELOPMENT = 0
    PROFILE_TYPE_ADHOC = 1
    PROFILE_TYPE_APPSTORE = 2
    _PROFILE_TYPE_LABELS = 'development adhoc appstore'.split()

    ALL_CERT_TYPES = "5QPB9NHCEI,R58UK2EWSO,9RQEK7MSXA,LA30L5BJEU,BKLRAVXMGM,3BQKVH9I2X,Y3B2F3TYSI"
    (CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION,
     CERT_TYPE_UNKNOWN_1, CERT_TYPE_UNKNOWN_2,
     CERT_TYPE_APN_DEVELOPMENT, CERT_TYPE_APN_PRODUCTION,
     CERT_TYPE_UNKNOWN_3) = ALL_CERT_TYPES.split(',')
    CERT_TYPE_IOS = [ CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION ]
