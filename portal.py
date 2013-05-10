#!/usr/bin/env python
from functools import wraps

import cookielib
import HTMLParser
import json
import os
import re
import sys
import urllib
import urllib2
import urlparse

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

def uuid():
    import uuid
    return str(uuid.uuid4())

class APIException(Exception):
    def __init__(self, info):
        super(APIException, self).__init__(
                '%s (Error %s: %s)' % (info['userString'], info['resultCode'], info['resultString']))
        self.info = info
        self.code = info['resultCode']

class API(object):
    LOGIN_URL = 'https://developer.apple.com/account/login.action'
    DEVELOPER_URL = 'https://developer.apple.com'
    DEVELOPER_SERVICES_URL = '%s/services-developerportal/QH65B2/account/ios' % DEVELOPER_URL

    GET_TEAM_ID_URL = 'https://developer.apple.com/account/ios/certificate/certificateList.action'

    class LoginHTMLParser(HTMLParser.HTMLParser):
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

    def __init__(self):
        cookie_jar = cookielib.CookieJar()
        processor = urllib2.HTTPCookieProcessor(cookie_jar)
        self.opener = urllib2.build_opener(processor)

    def login(self, user=None, password=None):
        try:
            r = self.opener.open(self.LOGIN_URL)
            assert r.getcode() == 200, "Unable to fetch login page"
            parser = self.LoginHTMLParser()
            parser.feed(r.read())
            assert parser.url, 'Unable to locate login post URL'
            scheme, netloc, _, _, _, _ = urlparse.urlparse(r.geturl())
            url = '%s://%s%s' % (scheme, netloc, parser.url)
            params = dict(theAccountName=user, theAccountPW=password,
                          theAuxValue='')
            r = self.opener.open(url, urllib.urlencode(params))
            assert r.getcode() == 200, "Unable to login"
            r = self.opener.open(self.GET_TEAM_ID_URL)
            assert r.getcode() == 200, "Unable to retrieve Team ID"
            matcher = re.search(r'teamId=([A-Z0-9]*)', r.read())
            assert matcher, "Unable to locate Team ID"
            self.team_id = matcher.group(1)
        except urllib2.URLError as e:
            raise e

    def _api(self, cmd, form={}, **kwargs):
        if isinstance(form, (dict, list)):
            form = urllib.urlencode(form)
        kwargs['content-type'] = 'text/x-url-arguments'
        kwargs['accept'] = 'application/json'
        kwargs['requestId'] = uuid()
        kwargs['userLocale'] = 'en_US'
        kwargs['teamId'] = self.team_id
        query = urllib.urlencode(kwargs)
        url = "%s/%s?%s" % (self.DEVELOPER_SERVICES_URL, cmd, query)
        response = self.opener.open(url, form)
        assert response.getcode() == 200, "Error %" % response.getcode()
        data = json.loads(response.read())
        rc = data['resultCode']
        if rc not in [ 0, 8500 ]:
            raise APIException(data)
        return data

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

    def download_profile(self, profile, filename):
        if isinstance(profile, dict):
            profile = profile['provisioningProfileId']
        url = self._make_dev_url('account/ios/profile/profileContentDownload',
                displayId=profile)
        r = self.opener.open(url)
        assert r.getcode() == 200, 'Unable to download profile [%s]' % profile
        dirname = os.path.dirname(filename)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)
        assert not dirname or os.path.isdir(dirname), "Path %s is not a directory" % dirname
        with open(filename, 'wb') as f:
            f.write(r.read())

    ALL_CERT_TYPES = "5QPB9NHCEI,R58UK2EWSO,9RQEK7MSXA,LA30L5BJEU,BKLRAVXMGM,3BQKVH9I2X,Y3B2F3TYSI"
    (CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION,
     CERT_TYPE_UNKNOWN_1, CERT_TYPE_UNKNOWN_2,
     CERT_TYPE_APN_DEVELOPMENT, CERT_TYPE_APN_PRODUCTION,
     CERT_TYPE_UNKNOWN_3) = ALL_CERT_TYPES.split(',')
    CERT_TYPE_IOS = [ CERT_TYPE_IOS_DEVELOPMENT, CERT_TYPE_IOS_DISTRIBUTION ]

if __name__ == '__main__':
    import getopt
    optlist, args = getopt.getopt(sys.argv[1:], 'u:p:a:')
    opts = dict((o[1:], a or True) for o, a in optlist)

    api = API()
    api.login(opts.get('u', 'admin@friendgraph.com'),
              opts.get('p', 'Fr13ndgr4ph'))
    if args[0] == 'update-profiles':
        dev_certs = api.list_cert_requests(typ=api.CERT_TYPE_IOS_DEVELOPMENT)
        dist_certs = api.list_cert_requests(typ=api.CERT_TYPE_IOS_DISTRIBUTION)
        devices = api.all_devices()
        profiles =  api.all_provisioning_profiles()
        for profile in profiles:
            identifier = profile['appId']['identifier']
            if 'a' in opts and identifier != opts['a']:
                continue
            if 'DISTRO' in profile['name']:
                is_appstore = True
                is_dev = is_adhoc = False
            print >>sys.stderr, identifier
            devs = devices if profile['deviceCount'] and 'DISTRO' not in profile['name'] and 'AppStore' not in profile['name'] else []
            certs = dev_certs if profile['type'] == 'Development' else dist_certs
            api.update_provisioning_profile(profile,
                    device_ids=devs, certificate_ids=certs)
    elif args[0] == 'download-profiles':
        profiles =  api.all_provisioning_profiles()
        for profile in profiles:
            identifier = profile['appId']['identifier']
            if 'a' in opts and identifier != opts['a']:
                continue
            is_wildcard = identifier == '*'
            is_dev = profile['type'] == 'Development'
            is_adhoc = not is_dev and profile['deviceCount'] > 0
            is_appstore = not is_dev and not is_adhoc
            if is_dev:
                filename = 'development.mobileprovision'
            elif is_adhoc:
                filename = 'adhoc.mobileprovision'
            else:
                filename = 'appstore.mobileprovision'
            if not is_wildcard:
                filename = '%s/%s' % (identifier, filename)
            api.download_profile(profile, filename)
    else:
        profiles = api.all_provisioning_profiles()
        print json.dumps([ p for p in profiles if p['name'].startswith('Test') ], indent=4)
