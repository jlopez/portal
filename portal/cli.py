#!/usr/bin/env python
import getopt
import os
import sys

import portal

opts = {}
api = portal.API()

def error(msg):
    print >>sys.stderr, msg
    sys.exit(1)

def usage():
    error("""usage: portal CMD [OPTS...] [ARGS...]

Certificate Management:
  portal listCertificates [-v | -r]

Device Management:
  portal listDevices [-v | -r]

App ID Management
  portal listApps [-v | -r]

Provisioning Profile Management:
  portal listProfiles [-v | -r]
  portal getProfile [-a | -i ID] [-o OUTPUT] [-q]
  portal regenerateProfile [-v | -q] [-n] [-a | [ID...]]
    """)

def camelcase_to_underscore(name):
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

CMDS = {
    'listCertificates': dict(getopt='vr'),
    'listDevices': dict(getopt='vr'),
    'listApps': dict(getopt='vr'),
    'listProfiles': dict(getopt='vr'),
    'getProfile': dict(getopt='qai:o:'),
    'regenerateProfile': dict(getopt='qanv'),
}

def main():
    try:
        sys.argv.pop(0)
        if not sys.argv:
            usage()
        cmd = sys.argv.pop(0)
        cmd_entry = CMDS.get(cmd)
        if cmd_entry is None:
            error("Unknown command '%s'")
        fn_name = 'cmd_%s' % camelcase_to_underscore(cmd).replace('-', '_')
        cmd_fn = globals()[fn_name]
        args = sys.argv
        argc_spec = cmd_entry.get('argc')
        if argc_spec:
            argc = len(args)
            if not isinstance(argc_spec, tuple):
                argc_spec = (argc_spec, argc_spec)
            if not argc_spec[0] <= argc <= argc_spec[1]:
                error("Incorrect args for '%s': Got %s, expected %s" %
                    (cmd, argc, argc_spec))
        spec = cmd_entry.get('getopt', '')
        spec = 'd' + spec
        optlist, args = getopt.getopt(args, spec)
        opts.update(dict((o[1:], a or True) for o, a in optlist))
        api.debug = 'd' in opts
        if not cmd_entry.get('no_login', False):
            api.login()
        return cmd_fn(*args)
    except KeyboardInterrupt:
        sys.exit(3)
    except getopt.GetoptError as e:
        error('portal %s: %s' % (cmd, e.msg))
    except (CLIError, portal.APIException) as e:
        error('portal %s: %s' % (cmd, e.message))

class CLIError(Exception): pass

def cmd_list_certificates():
    keys = ('certificateId expirationDate dateRequested dateCreated ' +
            'statusString typeString name' if 'v' in opts else
            'certificateId expirationDate typeString name').split()
    certs = api.list_cert_requests(typ=
        [api.CERT_TYPE_IOS_DEVELOPMENT, api.CERT_TYPE_IOS_DISTRIBUTION])
    for certificate in certs:
        if 'r' in opts:
            print certificate
        else:
            print '\t'.join(certificate[k] for k in keys)

def cmd_list_apps():
    keys = ('appIdId f1 f2 f3 f4 f5 f6 identifier name' if 'v' in opts else
            'appIdId identifier name').split()
    fkeys = 'inAppPurchase iCloud gameCenter push passbook dataProtection'.split()
    for app in api.all_app_ids():
        if 'r' in opts:
            print app
        else:
            if 'v' in opts:
                features = app['features']
                app.update({'f%d' % i: 'X' for i, k in enumerate(fkeys) if features[k]})
            print '\t'.join(app.get(k, '') for k in keys)

def cmd_list_devices():
    keys = ('deviceId status deviceNumber name' if 'v' in opts else
            'deviceNumber name').split()
    for device in api.all_devices():
        if 'r' in opts:
            print device
        else:
            print '\t'.join(device[k] for k in keys)

def cmd_list_profiles():
    for profile in api.all_provisioning_profiles():
        if 'r' in opts:
            print profile
        elif 'v' in opts:
            print '\t'.join(str(v) for v in (
                profile['provisioningProfileId'],
                profile['status'],
                profile['certificateCount'],
                profile['deviceCount'],
                profile['dateExpire'],
                api.profile_type(profile),
                profile['appId']['identifier'],
                profile['name']))
        else:
            print '\t'.join((
                profile['provisioningProfileId'],
                api.profile_type(profile),
                profile['appId']['identifier'],
                profile['name']))

def cmd_get_profile():
    if 'a' in opts:
        if 'i' in opts:
            raise CLIError("-i may not be specified with -a")
        path = opts.get('o', os.getcwd())
        profiles = api.all_provisioning_profiles()
        for ix, profile in enumerate(profiles):
            identifier = profile['appId']['identifier']
            filename = '%s.mobileprovision' % api.profile_type(profile)
            if identifier == '*':
                filename = os.path.join(path, filename)
            else:
                filename = os.path.join(path, identifier, filename)
            api.download_profile(profile, filename)
            if 'q' not in opts:
                print >>sys.stderr, '\rDownloading %d/%d profiles (%d%%)' % (
                        ix, len(profiles), ix * 100 / len(profiles)),
        if 'q' not in opts:
            print >>sys.stderr, '\n'
    elif 'i' in opts:
        api.download_profile(opts['i'], opts.get('o', sys.stdout))
    else:
        raise CLIError('One of -i or -a should be specified')

def cmd_regenerate_profile(*args):
    if not args and 'a' not in opts:
        raise CLIError('Must specify at least one profile (or use -a)')
    dev_certs = api.list_cert_requests(typ=api.CERT_TYPE_IOS_DEVELOPMENT)
    dist_certs = api.list_cert_requests(typ=api.CERT_TYPE_IOS_DISTRIBUTION)
    devices = api.all_devices()
    profiles =  api.all_provisioning_profiles()
    for ix, profile in enumerate(profiles):
        profile_id = profile['provisioningProfileId']
        if 'a' not in opts and profile_id not in args:
            continue
        profile_type = api.profile_type(profile)
        devs = [] if profile_type == 'appstore' else devices
        if (not api.is_profile_expired(profile) and
                profile['deviceCount'] == len(devs)):
            if 'v' in opts:
                print >>sys.stderr, '\rSkipping %s (%s)' % (
                        profile_id, profile['name'])
            continue
        certs = dev_certs if profile_type == 'development' else dist_certs
        if 'v' not in opts and 'q' not in opts:
            print >>sys.stderr, '\rRegenerating %d/%d profiles (%d%%)' % (
                    ix, len(profiles), ix * 100 / len(profiles)),
        if 'v' in opts:
            print >>sys.stderr, '\rRegenerating %s (%s)' % (
                    profile_id, profile['name'])
        if 'n' not in opts:
            api.update_provisioning_profile(profile,
                    device_ids=devs, certificate_ids=certs)
