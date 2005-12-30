# -*- coding: iso-8859-1 -*-
"""
    MoinMoin - Multiple configuration handler and Configuration defaults class

    @copyright: 2000-2004 by J�rgen Hermann <jh@web.de>
    @license: GNU GPL, see COPYING for details.
"""

import re, os, sys
from MoinMoin import error
import MoinMoin.auth as authmodule

_url_re_cache = None
_farmconfig_mtime = None
_config_cache = {}


def _importConfigModule(name):
    """ Import and return configuration module and its modification time
    
    Handle all errors except ImportError, because missing file is not
    always an error.
    
    @param name: module name
    @rtype: tuple
    @return: module, modification time
    """
    try:
        module = __import__(name, globals(), {})
        mtime = os.path.getmtime(module.__file__)
    except ImportError:
        raise
    except IndentationError, err:
        msg = 'IndentationError: %s\n' % str(err) + '''

The configuration files are python modules. Therefore, whitespace is
important. Make sure that you use only spaces, no tabs are allowed here!
You have to use four spaces at the beginning of the line mostly.
'''
        raise error.ConfigurationError(msg)
    except Exception, err:
        msg = '%s: %s' % (err.__class__.__name__, str(err))
        raise error.ConfigurationError(msg)
    return module, mtime


def _url_re():
    """ Return url matching regular expression

    Import wikis list from farmconfig on the first call and compile a
    regex. Later then return the cached regex.

    @rtype: compiled re object
    @return: url to wiki config  matching re
    """
    global _url_re_cache, _farmconfig_mtime
    if _url_re_cache is None:
        try:
            farmconfig, _farmconfig_mtime = _importConfigModule('farmconfig')
        except ImportError:
            # Default to wikiconfig for all urls.
            _farmconfig_mtime = 0
            _url_re_cache = re.compile(r'(?P<wikiconfig>.)')
        else:
            try:
                pattern = '|'.join([r'(?P<%s>%s)' % (name, regex)
                                    for name, regex in farmconfig.wikis])
                _url_re_cache = re.compile(pattern)
            except AttributeError:
                msg = """
Missing required 'wikis' list in 'farmconfig.py'.

If you run a single wiki you do not need farmconfig.py. Delete it and
use wikiconfig.py.
"""
                raise error.ConfigurationError(msg)    
    return _url_re_cache


def _makeConfig(name):
    """ Create and return a config instance 

    Timestamp config with either module mtime or farmconfig mtime. This
    mtime can be used later to invalidate older caches.

    @param name: module name
    @rtype: DefaultConfig sub class instance
    @return: new configuration instance
    """
    global _farmconfig_mtime
    try:
        module, mtime = _importConfigModule(name)
        configClass = getattr(module, 'Config')
        cfg = configClass(name)
        cfg.cfg_mtime = max(mtime, _farmconfig_mtime)
    except ImportError, err:
        msg = 'ImportError: %s\n' % str(err) + '''

Check that the file is in the same directory as the server script. If
it is not, you must add the path of the directory where the file is
located to the python path in the server script. See the comments at
the top of the server script.

Check that the configuration file name is either "wikiconfig.py" or the
module name specified in the wikis list in farmconfig.py. Note that the
module name does not include the ".py" suffix.
'''
        raise error.ConfigurationError(msg)
    except AttributeError:
        msg = '''
Could not find required "Config" class in "%(name)s.py". This might
happen if you are trying to use a pre 1.3 configuration file, or made a
syntax or spelling error.

Please check your configuration file. As an example for correct syntax,
use the wikiconfig.py file from the distribution.
''' % {'name': name}
        raise error.ConfigurationError(msg)
    return cfg


def _getConfigName(url):
    """ Return config name for url or raise """
    match = _url_re().match(url)
    if not (match and match.groups()):
        msg = '''
Could not find a match for url: "%(url)s".

Check your URL regular expressions in the "wikis" list in
"farmconfig.py". 
''' % {'url': url}
        raise error.ConfigurationError(msg)    
    for name, value in match.groupdict().items():
        if value: break
    return name


def getConfig(url):
    """ Return cached config instance for url or create new one

    If called by many threads in the same time multiple config
    instances might be created. The first created item will be
    returned, using dict.setdefault.

    @param url: the url from request, possibly matching specific wiki
    @rtype: DefaultConfig subclass instance
    @return: config object for specific wiki
    """
    configName = _getConfigName(url)
    try:
        config = _config_cache[configName]
    except KeyError:
        config = _makeConfig(configName)
        config = _config_cache.setdefault(configName, config)
    return config


# This is a way to mark some text for the gettext tools so that they don't
# get orphaned. See http://www.python.org/doc/current/lib/node278.html.
def _(text): return text


class DefaultConfig:
    """ default config values """
    
    # All acl_right lines must use unicode!
    acl_rights_default = u"Trusted:read,write,delete,revert Known:read,write,delete,revert All:read,write"
    acl_rights_before = u""
    acl_rights_after = u""
    acl_rights_valid = ['read', 'write', 'delete', 'revert', 'admin']
    
    actions_excluded = [] # ['DeletePage', 'AttachFile', 'RenamePage']
    allow_xslt = 0
    attachments = None # {'dir': path, 'url': url-prefix}
    auth = [authmodule.moin_cookie]
    
    backup_compression = 'gz'
    backup_users = []
    backup_include = []
    backup_exclude = [
        r"(.+\.py(c|o)$)",
        r"%(cache_dir)s",
        r"%(/)spages%(/)s.+%(/)scache%(/)s[^%(/)s]+$" % {'/': os.sep},
        r"%(/)s(edit-lock|event-log|\.DS_Store)$" % {'/': os.sep},
        ]
    backup_storage_dir = '/tmp'
    backup_restore_target_dir = '/tmp'
    
    bang_meta = 1
    caching_formats = ['text_html']
    changed_time_fmt = '%H:%M'
    # chars_{upper,lower,digits,spaces} see MoinMoin/util/chartypes.py
    # if you have gdchart, add something like
    # chart_options = {'width = 720, 'height': 540}
    chart_options = None
    config_check_enabled = 0
    cookie_domain = None # use '.domain.tld" for a farm with hosts in that domain
    cookie_path = None   # use '/wikifarm" for a farm with pathes below that path
    cookie_lifetime = 12 # 12 hours from now
    data_dir = './data/'
    data_underlay_dir = './underlay/'
    date_fmt = '%Y-%m-%d'
    datetime_fmt = '%Y-%m-%d %H:%M:%S'
    default_markup = 'wiki'
    docbook_html_dir = r"/usr/share/xml/docbook/stylesheet/nwalsh/html/" # correct for debian sarge
    editor_default = 'text' # which editor is called when nothing is specified
    editor_ui = 'freechoice' # which editor links are shown on user interface
    editor_force = False
    edit_locking = 'warn 10' # None, 'warn <timeout mins>', 'lock <timeout mins>'
    edit_rows = 20
                
    hacks = {} # { 'feature1': value1, ... }
               # Configuration for features still in development.
               # For boolean stuff just use config like this:
               #   hacks = { 'feature': True, ...}
               # and in the code use:
               #   if cfg.hacks.get('feature', False): <doit>
               # A non-existing hack key should ever mean False, None, "", [] or {}!

    hosts_deny = []
    html_head = ''
    html_head_queries = '''<meta name="robots" content="noindex,nofollow">\n'''
    html_head_posts   = '''<meta name="robots" content="noindex,nofollow">\n'''
    html_head_index   = '''<meta name="robots" content="index,follow">\n'''
    html_head_normal  = '''<meta name="robots" content="index,nofollow">\n'''
    html_pagetitle = None

    interwiki_preferred = [] # list of wiki names to show at top of interwiki list

    language_default = 'en'
    language_ignore_browser = False # ignore browser settings, use language_default
                                    # or user prefs

    lupy_search = False # disabled until lupy is finished

    mail_login = None # or "user pwd" if you need to use SMTP AUTH
    mail_sendmail = None # "/usr/sbin/sendmail -t -i" to not use SMTP, but sendmail
    mail_smarthost = None
    mail_from = None # u'J�rgen Wiki <noreply@jhwiki.org>'
    
    navi_bar = [u'RecentChanges', u'FindPage', u'HelpContents', ]
    nonexist_qm = 0

    page_credits = [
        '<a href="http://moinmoin.wikiwikiweb.de/">MoinMoin Powered</a>',
        '<a href="http://www.python.org/">Python Powered</a>',
        '<a href="http://validator.w3.org/check?uri=referer">Valid HTML 4.01</a>',
        ]
    page_footer1 = ''
    page_footer2 = ''

    page_header1 = ''
    page_header2 = ''
    
    page_front_page = u'HelpOnLanguages' # this will make people choose a sane config
    page_local_spelling_words = u'LocalSpellingWords'
    page_category_regex = u'^Category[A-Z]'
    page_dict_regex = u'[a-z0-9]Dict$'
    page_form_regex = u'[a-z0-9]Form$'
    page_group_regex = u'[a-z0-9]Group$'
    page_template_regex = u'[a-z0-9]Template$'

    page_license_enabled = 0
    page_license_page = u'WikiLicense'

    # These icons will show in this order in the iconbar, unless they
    # are not relevant, e.g email icon when the wiki is not configured
    # for email.
    page_iconbar = ["up", "edit", "view", "diff", "info", "subscribe", "raw", "print",]

    # Standard buttons in the iconbar
    page_icons_table = {
        # key           last part of url, title, icon-key
        'help':        ("%(q_page_help_contents)s", "%(page_help_contents)s", "help"),
        'find':        ("%(q_page_find_page)s?value=%(q_page_name)s", "%(page_find_page)s", "find"),
        'diff':        ("%(q_page_name)s?action=diff", _("Diffs"), "diff"),
        'info':        ("%(q_page_name)s?action=info", _("Info"), "info"),
        'edit':        ("%(q_page_name)s?action=edit", _("Edit"), "edit"),
        'unsubscribe': ("%(q_page_name)s?action=subscribe", _("UnSubscribe"), "unsubscribe"),
        'subscribe':   ("%(q_page_name)s?action=subscribe", _("Subscribe"), "subscribe"),
        'raw':         ("%(q_page_name)s?action=raw", _("Raw"), "raw"),
        'xml':         ("%(q_page_name)s?action=format&amp;mimetype=text/xml", _("XML"), "xml"),
        'print':       ("%(q_page_name)s?action=print", _("Print"), "print"),
        'view':        ("%(q_page_name)s", _("View"), "view"),
        'up':          ("%(q_page_parent_page)s", _("Up"), "up"),
        }
    refresh = None # (minimum_delay, type), e.g.: (2, 'internal')
    rss_cache = 60 # suggested caching time for RecentChanges RSS, in seconds
    shared_intermap = None # can be string or list of strings (filenames)
    show_hosts = 1
    show_interwiki = 0
    show_login = 1
    show_section_numbers = 0
    show_timings = 0
    show_version = 0
    siteid = 'default'
    stylesheets = [] # list of tuples (media, csshref) to insert after theme css, before user css
    superuser = [] # list of unicode user names that have super powers :)
    theme_default = 'modern'
    theme_force = False
    trail_size = 5
    tz_offset = 0.0 # default time zone offset in hours from UTC
    user_autocreate = False # do we auto-create user profiles
    user_email_unique = True # do we check whether a user's email is unique?

    # a regex of HTTP_USER_AGENTS that should be excluded from logging
    # and receive a FORBIDDEN for anything except viewing a page
    ua_spiders = ('archiver|cfetch|crawler|curl|gigabot|google|holmes|htdig|httrack|httpunit|jeeves|larbin|leech|'
                  'linkbot|linkmap|linkwalk|mercator|mirror|msnbot|nutbot|omniexplorer|puf|robot|scooter|'
                  'search|sherlock|sitecheck|spider|teleport|wget')

    # Wiki identity
    sitename = u'Untitled Wiki'
    url_prefix = '/wiki'
    logo_string = None
    interwikiname = None
    
    url_mappings = {}

    user_checkbox_fields = [
        ('mailto_author', lambda _: _('Publish my email (not my wiki homepage) in author info')),
        ('edit_on_doubleclick', lambda _: _('Open editor on double click')),
        ('remember_last_visit', lambda _: _('Jump to last visited page instead of frontpage')),
        ('show_nonexist_qm', lambda _: _('Show question mark for non-existing pagelinks')),
        ('show_page_trail', lambda _: _('Show page trail')),
        ('show_toolbar', lambda _: _('Show icon toolbar')),
        ('show_topbottom', lambda _: _('Show top/bottom links in headings')),
        ('show_fancy_diff', lambda _: _('Show fancy diffs')),
        ('wikiname_add_spaces', lambda _: _('Add spaces to displayed wiki names')),
        ('remember_me', lambda _: _('Remember login information')),
        ('want_trivial', lambda _: _('Subscribe to trivial changes')),
        
        ('disabled', lambda _: _('Disable this account forever')),
        # if an account is disabled, it may be used for looking up
        # id -> username for page info and recent changes, but it
        # is not usable for the user any more:
    ]
    user_checkbox_defaults = {'mailto_author':       0,
                              'edit_on_doubleclick': 0,
                              'remember_last_visit': 0,
                              'show_nonexist_qm':    nonexist_qm,
                              'show_page_trail':     1,
                              'show_toolbar':        1,
                              'show_topbottom':      0,
                              'show_fancy_diff':     1,
                              'wikiname_add_spaces': 0,
                              'remember_me':         1,
                              'want_trivial':        0,
                             }
    # don't let the user change those
    # user_checkbox_disable = ['disabled', 'want_trivial']
    user_checkbox_disable = []
    
    # remove those checkboxes:
    #user_checkbox_remove = ['edit_on_doubleclick', 'show_nonexist_qm', 'show_toolbar', 'show_topbottom',
    #                        'show_fancy_diff', 'wikiname_add_spaces', 'remember_me', 'disabled',]
    user_checkbox_remove = []
    
    user_form_fields = [
        ('name', _('Name'), "text", "36", _("(Use Firstname''''''Lastname)")),
        ('aliasname', _('Alias-Name'), "text", "36", ''),
        ('password', _('Password'), "password", "36", ''),
        ('password2', _('Password repeat'), "password", "36", _('(Only when changing passwords)')),
        ('email', _('Email'), "text", "36", ''),
        ('css_url', _('User CSS URL'), "text", "40", _('(Leave it empty for disabling user CSS)')),
        ('edit_rows', _('Editor size'), "text", "3", ''),
        ##('theme', _('Preferred theme'), [self._theme_select()])
        ##('', _('Editor Preference'), [self._editor_default_select()])
        ##('', _('Editor shown on UI'), [self._editor_ui_select()])
        ##('', _('Time zone'), [self._tz_select()])
        ##('', _('Date format'), [self._dtfmt_select()])
        ##('', _('Preferred language'), [self._lang_select()])
    ]
    user_form_defaults = { # key: default
        'name': '',
        'aliasname': '',
        'password': '',
        'password2': '',
        'email': '',
        'css_url': '',
        'edit_rows': "20",
    }
    # don't let the user change those, but show them:
    #user_form_disable = ['name', 'aliasname', 'email',]
    user_form_disable = []
    
    # remove those completely:
    #user_form_remove = ['password', 'password2', 'css_url', 'logout', 'create', 'account_sendmail',]
    user_form_remove = []
    
    # attributes we do NOT save to the userpref file
    user_transient_fields =  ['id', 'valid', 'may', 'auth_username', 'trusted', 'password', 'password2', 'auth_method', 'auth_attribs']

    user_homewiki = 'Self' # interwiki name for where user homepages are located

    unzip_single_file_size = 2.0 * 1000**2
    unzip_attachments_space = 200.0 * 1000**2
    unzip_attachments_count = 51 # 1 zip file + 50 files contained in it

    xmlrpc_putpage_enabled = 0 # if 0, putpage will write to a test page only
    xmlrpc_putpage_trusted_only = 1 # if 1, you will need to be http auth authenticated
    
    SecurityPolicy = None

    def __init__(self, siteid):
        """ Init Config instance """
        self.siteid = siteid
        if self.config_check_enabled:
            self._config_check()

        # define directories
        self.moinmoin_dir = os.path.abspath(os.path.dirname(__file__))
        data_dir = os.path.normpath(self.data_dir)
        self.data_dir = data_dir
        for dirname in ('user', 'cache', 'plugin'):
            name = dirname + '_dir'
            if not getattr(self, name, None):
                setattr(self, name, os.path.join(data_dir, dirname))
            
        # Try to decode certain names which allow unicode
        self._decode()

        # Make sure directories are accessible
        self._check_directories()

        # Load plugin module
        self._loadPluginModule()

        # Preparse user dicts
        self._fillDicts()
        
        # Normalize values
        self.language_default = self.language_default.lower()

        # Use site name as default name-logo
        if self.logo_string is None:
            self.logo_string = self.sitename

        # Check for needed modules

        # FIXME: maybe we should do this check later, just before a
        # chart is needed, maybe in the chart module, instead doing it
        # for each request. But this require a large refactoring of
        # current code.
        if self.chart_options:
            try:
                import gdchart
            except ImportError:
                self.chart_options = None
        
        # post process
        # we replace any string placeholders with config values
        # e.g u'%(page_front_page)s' % self
        self.navi_bar = [elem % self for elem in self.navi_bar]
        self.backup_exclude = [elem % self for elem in self.backup_exclude]

        # list to cache lupy searcher objects
        self.lupy_searchers = []

        # check if mail is possible and set flag:
        self.mail_enabled = not (self.mail_smarthost is None and self.mail_sendmail is None)

    def _config_check(self):
        """ Check namespace and warn about unknown names
        
        Warn about names which are not used by DefaultConfig, except
        modules, classes, _private or __magic__ names.

        This check is disabled by default, when enabled, it will show an
        error message with unknown names.
        """       
        unknown = ['"%s"' % name for name in dir(self)
                  if not name.startswith('_') and 
                  not DefaultConfig.__dict__.has_key(name) and
                  not isinstance(getattr(self, name), (type(sys), type(DefaultConfig)))]
        if unknown:
            msg = """
Unknown configuration options: %s.

For more information, visit HelpOnConfiguration. Please check your
configuration for typos before requesting support or reporting a bug.
""" % ', '.join(unknown)
            raise error.ConfigurationError(msg)

    def _decode(self):
        """ Try to decode certain names, ignore unicode values
        
        Try to decode str using utf-8. If the decode fail, raise FatalError. 

        Certain config variables should contain unicode values, and
        should be defined with u'text' syntax. Python decode these if
        the file have a 'coding' line.
        
        This will allow utf-8 users to use simple strings using, without
        using u'string'. Other users will have to use u'string' for
        these names, because we don't know what is the charset of the
        config files.
        """
        charset = 'utf-8'
        message = u'''
"%(name)s" configuration variable is a string, but should be
unicode. Use %(name)s = u"value" syntax for unicode variables.

Also check your "-*- coding -*-" line at the top of your configuration
file. It should match the actual charset of the configuration file.
'''
        
        decode_names = (
            'sitename', 'logo_string', 'navi_bar', 'page_front_page',
            'page_category_regex', 'page_dict_regex', 'page_form_regex',
            'page_group_regex', 'page_template_regex', 'page_license_page',
            'page_local_spelling_words', 'acl_rights_default',
            'acl_rights_before', 'acl_rights_after', 'mail_from'
            )
        
        for name in decode_names:
            attr = getattr(self, name, None)
            if attr:
                # Try to decode strings
                if isinstance(attr, str):
                    try:
                        setattr(self, name, unicode(attr, charset)) 
                    except UnicodeError:
                        raise error.ConfigurationError(message %
                                                       {'name': name})
                # Look into lists and try to decode strings inside them
                elif isinstance(attr, list):
                    for i in xrange(len(attr)):
                        item = attr[i]
                        if isinstance(item, str):
                            try:
                                attr[i] = unicode(item, charset)
                            except UnicodeError:
                                raise error.ConfigurationError(message %
                                                               {'name': name})

    def _check_directories(self):
        """ Make sure directories are accessible

        Both data and underlay should exists and allow read, write and
        execute.
        """
        mode = os.F_OK | os.R_OK | os.W_OK | os.X_OK
        for attr in ('data_dir', 'data_underlay_dir'):
            path = getattr(self, attr)
            
            # allow an empty underlay path or None
            if attr == 'data_underlay_dir' and not path:
                continue

            path_pages = os.path.join(path, "pages")
            if not (os.path.isdir(path_pages) and os.access(path_pages, mode)):
                msg = '''
%(attr)s "%(path)s" does not exists, or has incorrect ownership or
permissions.

Make sure the directory and the subdirectory pages are owned by the web
server and are readable, writable and executable by the web server user
and group.

It is recommended to use absolute paths and not relative paths. Check
also the spelling of the directory name.
''' % {'attr': attr, 'path': path,}
                raise error.ConfigurationError(msg)

    def _loadPluginModule(self):
        """ import plugin module under configname.plugin

        To be able to import plugin from arbitrary path, we have to load
        the base package once using imp.load_module. Later, we can use
        standard __import__ call to load plugins in this package.

        Since each wiki has unique plugins, we load the plugin package
        under the wiki configuration module, named self.siteid.
        """
        import sys, imp

        name = self.siteid + '.plugin'
        try:
            # Lock other threads while we check and import
            imp.acquire_lock()
            try:
                # If the module is not loaded, try to load it
                if not name in sys.modules:
                    # Find module on disk and try to load - slow!
                    plugin_parent_dir = os.path.abspath(os.path.join(self.plugin_dir, '..'))
                    fp, path, info = imp.find_module('plugin', [plugin_parent_dir])
                    try:
                        # Load the module and set in sys.modules             
                        module = imp.load_module(name, fp, path, info)
                        sys.modules[self.siteid].plugin = module
                    finally:
                        # Make sure fp is closed properly
                        if fp:
                            fp.close()
            finally:
                imp.release_lock()
        except ImportError, err:
            msg = '''
Could not import plugin package "%(path)s/plugin" because of ImportError:
%(err)s.

Make sure your data directory path is correct, check permissions, and
that the data/plugin directory has an __init__.py file.
''' % {'path': self.data_dir, 'err': str(err)}
            raise error.ConfigurationError(msg)

    def _fillDicts(self):
        """ fill config dicts

        Fills in missing dict keys of derived user config by copying
        them from this base class.
        """
        # user checkbox defaults
        for key, value in DefaultConfig.user_checkbox_defaults.items():
            if not self.user_checkbox_defaults.has_key(key):
                self.user_checkbox_defaults[key] = value

    def __getitem__(self, item):
        """ Make it possible to access a config object like a dict """
        return getattr(self, item)
    
# remove the gettext pseudo function 
del _

