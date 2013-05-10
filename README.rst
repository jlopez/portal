Portal
======
Portal is a Python module that hooks to Apple's undocumented provisioning
portal developer services as well as a command line utility that allows
you to perform tasks without suffering CTS from all the clicking.

Not all functionality is available, it will be added as time permits.

CLI
---
Usage::

  usage: portal CMD [OPTS...] [ARGS...]

  Certificate Management:
    portal listCertificates [-v | -r]

  Device Management:
    portal listDevices [-v | -r]

  App ID Management
    portal listApps [-v | -r]

  Provisioning Profile Management:
    portal listProfiles [-v | -r] <filter-criteria>
    portal getProfile [-a | -i ID] [-o OUTPUT] [-q]
    portal regenerateProfile [-v | -q] [-n] [-a | [ID...]]
    portal deleteProfile [-q] [-n] <filter-criteria>
    filter-criteria: [-t type] [-i appId] [-r nameregex] [ID...]



API
---
Sample usage::

  import portal

  # Instantiate and login
  api = portal.API()
  api.login('user@email.com', 'mypassword')

  # Retrieve all provisioning profiles
  profiles = api.all_provisioning_profiles()

  # Download the one matching a specific name
  matches = [ p for p in profiles if profile['name'] = 'MyApp' ]
  api.download_profile(p, 'myapp.mobileprovision')

  # Other api methods:
  api.all_cert_requests()
  api.all_app_ids()
  api.all_provisioning_profiles()
  api.all_devices()
  api.clear_cache() # all the all_* methods cache their results.
                    # clear_cache will force a refetch
  api.list_cert_requests(types) # get certs matching any of the listed types
                                # e.g. CERT_TYPE_IOS_DEVELOPMENT, etc.
  api.update_provisioning_profile(profile, ...) # update a provisioning profile
  api.download_profile(profile, path) # Download a provisioning profile
  api.delete_provisioning_profile(...)
  api.create_provisioning_profile(...)
