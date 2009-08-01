# -*- coding: iso-8859-1 -*-
"""
    MoinMoin - search engine internals

    @copyright: 2005 MoinMoin:FlorianFesti,
                2005 MoinMoin:NirSoffer,
                2005 MoinMoin:AlexanderSchremmer,
                2006-2008 MoinMoin:ThomasWaldmann,
                2006 MoinMoin:FranzPletz
    @license: GNU GPL, see COPYING for details
"""

import sys, os, time, errno, codecs

from MoinMoin import log
logging = log.getLogger(__name__)

from MoinMoin import wikiutil, config
from MoinMoin.Page import Page
from MoinMoin.util import lock, filesys
from MoinMoin.search.results import getSearchResults
from MoinMoin.search.queryparser import Match, TextMatch, TitleMatch

##############################################################################
# Search Engine Abstraction
##############################################################################

class UpdateQueue:
    """ Represents a locked page queue on the disk

        XXX: check whether we just can use the caching module
    """

    def __init__(self, f, lock_dir):
        """
        @param f: file to write to
        @param lock_dir: directory to save the lock files
        """
        self.file = f
        self.writeLock = lock.WriteLock(lock_dir, timeout=10.0)
        self.readLock = lock.ReadLock(lock_dir, timeout=10.0)

    def exists(self):
        """ Checks if the queue exists on the filesystem """
        return os.path.exists(self.file)

    def append(self, pagename):
        """ Append a page to queue

        @param pagename: string to save
        """
        if not self.writeLock.acquire(60.0):
            logging.warning("can't add %r to xapian update queue: can't lock queue" % pagename)
            return
        try:
            f = codecs.open(self.file, 'a', config.charset)
            try:
                f.write(pagename + "\n")
            finally:
                f.close()
        finally:
            self.writeLock.release()

    def pages(self):
        """ Return list of pages in the queue """
        if self.readLock.acquire(1.0):
            try:
                return self._decode(self._read())
            finally:
                self.readLock.release()
        return []

    def remove(self, pages):
        """ Remove pages from the queue

        When the queue is empty, the queue file is removed, so exists()
        can tell if there is something waiting in the queue.

        @param pages: list of pagenames to remove
        """
        if self.writeLock.acquire(30.0):
            try:
                queue = self._decode(self._read())
                for page in pages:
                    try:
                        queue.remove(page)
                    except ValueError:
                        pass
                if queue:
                    self._write(queue)
                else:
                    self._removeFile()
                return True
            finally:
                self.writeLock.release()
        return False

    # Private -------------------------------------------------------

    def _decode(self, data):
        """ Decode queue data

        @param data: the data to decode
        """
        pages = data.splitlines()
        return self._filterDuplicates(pages)

    def _filterDuplicates(self, pages):
        """ Filter duplicates in page list, keeping the order

        @param pages: list of pages to filter
        """
        unique = []
        seen = {}
        for name in pages:
            if not name in seen:
                unique.append(name)
                seen[name] = 1
        return unique

    def _read(self):
        """ Read and return queue data

        This does not do anything with the data so we can release the
        lock as soon as possible, enabling others to update the queue.
        """
        try:
            f = codecs.open(self.file, 'r', config.charset)
            try:
                return f.read()
            finally:
                f.close()
        except (OSError, IOError), err:
            if err.errno != errno.ENOENT:
                raise
            return ''

    def _write(self, pages):
        """ Write pages to queue file

        Requires queue write locking.

        @param pages: list of pages to write
        """
        # XXX use tmpfile/move for atomic replace on real operating systems
        data = '\n'.join(pages) + '\n'
        f = codecs.open(self.file, 'w', config.charset)
        try:
            f.write(data)
        finally:
            f.close()

    def _removeFile(self):
        """ Remove queue file

        Requires queue write locking.
        """
        try:
            os.remove(self.file)
        except OSError, err:
            if err.errno != errno.ENOENT:
                raise


class BaseIndex:
    """ Represents a search engine index """

    class LockedException(Exception):
        pass

    def __init__(self, request):
        """
        @param request: current request
        """
        self.request = request
        main_dir = self._main_dir()
        self.dir = os.path.join(main_dir, 'index')
        if not os.path.exists(self.dir):
            os.makedirs(self.dir)
        self.sig_file = os.path.join(main_dir, 'complete')
        lock_dir = os.path.join(main_dir, 'index-lock')
        self.lock = lock.WriteLock(lock_dir, timeout=3600.0, readlocktimeout=60.0)
        #self.read_lock = lock.ReadLock(lock_dir, timeout=3600.0)
        self.update_queue = UpdateQueue(os.path.join(main_dir, 'update-queue'),
                                os.path.join(main_dir, 'update-queue-lock'))
        self.remove_queue = UpdateQueue(os.path.join(main_dir, 'remove-queue'),
                                os.path.join(main_dir, 'remove-queue-lock'))

        # Disabled until we have a sane way to build the index with a
        # queue in small steps.
        ## if not self.exists():
        ##    self.indexPagesInNewThread(request)

    def _main_dir(self):
        raise NotImplemented('...')

    def exists(self):
        """ Check if index exists """
        return os.path.exists(self.sig_file)

    def mtime(self):
        """ Modification time of the index """
        return os.path.getmtime(self.dir)

    def touch(self):
        """ Touch the index """
        filesys.touch(self.dir)

    def _search(self, query):
        """ Actually perfom the search (read-lock acquired)

        @param query: the search query objects tree
        """
        raise NotImplemented('...')

    def search(self, query, **kw):
        """ Search for items in the index

        @param query: the search query objects to pass to the index
        """
        #if not self.read_lock.acquire(1.0):
        #    raise self.LockedException
        #try:
        hits = self._search(query, **kw)
        #finally:
        #    self.read_lock.release()
        return hits

    def update_page(self, pagename, now=1):
        """ Update a single page in the index

        @param pagename: the name of the page to update
        @keyword now: do all updates now (default: 1)
        """
        self.update_queue.append(pagename)
        if now:
            self._do_queued_updates_InNewThread()

    def remove_item(self, pagename, attachment=None, now=1):
        """ Removes a page and all its revisions or a single attachment

        @param pagename: name of the page to be removed
        @keyword attachment: optional, only remove this attachment of the page
        @keyword now: do all updates now (default: 1)
        """
        self.remove_queue.append('%s//%s' % (pagename, attachment or ''))
        if now:
            self._do_queued_updates_InNewThread()

    def indexPages(self, files=None, mode='update'):
        """ Index all pages (and files, if given)

        Can be called only from a script. To index pages during a user
        request, use indexPagesInNewThread.
        @keyword files: iterator or list of files to index additionally
        @keyword mode: set the mode of indexing the pages, either 'update', 'add' or 'rebuild'
        """
        if not self.lock.acquire(1.0):
            logging.warning("can't index: can't acquire lock")
            return
        try:
            self._unsign()
            start = time.time()
            request = self._indexingRequest(self.request)
            self._index_pages(request, files, mode)
            logging.info("indexing completed successfully in %0.2f seconds." %
                        (time.time() - start))
            self._sign()
        finally:
            self.lock.release()

    def indexPagesInNewThread(self, files=None, mode='update'):
        """ Index all pages in a new thread

        Should be called from a user request. From a script, use indexPages.
        """
        # Prevent rebuilding the index just after it was finished
        if self.exists():
            return

        from threading import Thread
        indexThread = Thread(target=self._index_pages, args=(self.request, files, mode))
        indexThread.setDaemon(True)

        # Join the index thread after current request finish, prevent
        # Apache CGI from killing the process.
        def joinDecorator(finish):
            def func():
                finish()
                indexThread.join()
            return func

        self.request.finish = joinDecorator(self.request.finish)
        indexThread.start()

    def _index_pages(self, request, files=None, mode='update'):
        """ Index all pages (and all given files)

        This should be called from indexPages or indexPagesInNewThread only!

        This may take some time, depending on the size of the wiki and speed
        of the machine.

        When called in a new thread, lock is acquired before the call,
        and this method must release it when it finishes or fails.

        @param request: current request
        @keyword files: iterator or list of files to index additionally
        @keyword mode: set the mode of indexing the pages, either 'update',
        'add' or 'rebuild'
        """
        raise NotImplemented('...')

    def _remove_item(self, writer, page, attachment=None):
        """ Remove a page and all its revisions from the index or just
            an attachment of that page

        @param pagename: name of the page to remove
        @keyword attachment: optionally, just remove this attachment
        """
        raise NotImplemented('...')

    def _do_queued_updates_InNewThread(self):
        """ do queued index updates in a new thread

        Should be called from a user request. From a script, use indexPages.
        """
        if not self.lock.acquire(1.0):
            logging.warning("can't index: can't acquire lock")
            return
        try:
            def lockedDecorator(f):
                def func(*args, **kwargs):
                    try:
                        return f(*args, **kwargs)
                    finally:
                        self.lock.release()
                return func

            from threading import Thread
            indexThread = Thread(
                    target=lockedDecorator(self._do_queued_updates),
                    args=(self._indexingRequest(self.request), ))
            indexThread.setDaemon(True)

            # Join the index thread after current request finish, prevent
            # Apache CGI from killing the process.
            def joinDecorator(finish):
                def func():
                    finish()
                    indexThread.join()
                return func

            self.request.finish = joinDecorator(self.request.finish)
            indexThread.start()
        except:
            self.lock.release()
            raise

    def _do_queued_updates(self, request, amount=5):
        """ Perform updates in the queues (read-lock acquired)

        @param request: the current request
        @keyword amount: how many updates to perform at once (default: 5)
        """
        raise NotImplemented('...')

    def optimize(self):
        """ Optimize the index if possible """
        raise NotImplemented('...')

    def contentfilter(self, filename):
        """ Get a filter for content of filename and return unicode content.

        @param filename: name of the file
        """
        request = self.request
        mt = wikiutil.MimeType(filename=filename)
        for modulename in mt.module_name():
            try:
                execute = wikiutil.importPlugin(request.cfg, 'filter', modulename)
                break
            except wikiutil.PluginMissingError:
                pass
            else:
                logging.info("Cannot load filter for mimetype %s" % modulename)
        try:
            data = execute(self, filename)
            logging.debug("Filter %s returned %d characters for file %s" % (modulename, len(data), filename))
        except (OSError, IOError), err:
            data = ''
            logging.warning("Filter %s threw error '%s' for file %s" % (modulename, str(err), filename))
        return mt.mime_type(), data

    def _indexingRequest(self, request):
        """ Return a new request that can be used for index building.

        This request uses a security policy that lets the current user
        read any page. Without this policy some pages will not render,
        which will create broken pagelinks index.

        @param request: current request
        """
        from MoinMoin.web.contexts import ScriptContext
        from MoinMoin.security import Permissions
        from MoinMoin.logfile import editlog
        r = ScriptContext(request.url)
        class SecurityPolicy(Permissions):
            def read(self, *args, **kw):
                return True
        r.user.may = SecurityPolicy(r.user)
        r.editlog = editlog.EditLog(r)
        return r

    def _unsign(self):
        """ Remove sig file - assume write lock acquired """
        try:
            os.remove(self.sig_file)
        except OSError, err:
            if err.errno != errno.ENOENT:
                raise

    def _sign(self):
        """ Add sig file - assume write lock acquired """
        f = file(self.sig_file, 'w')
        try:
            f.write('')
        finally:
            f.close()


##############################################################################
### Searching
##############################################################################

class BaseSearch(object):
    """ A search run """

    def __init__(self, request, query, sort='weight', mtime=None, historysearch=0):
        """
        @param request: current request
        @param query: search query objects tree
        @keyword sort: the sorting of the results (default: 'weight')
        @keyword mtime: only show items newer than this timestamp (default: None)
        @keyword historysearch: whether to show old revisions of a page (default: 0)
        """
        self.request = request
        self.query = query
        self.sort = sort
        self.mtime = mtime
        self.historysearch = historysearch
        self.filtered = False
        self.fs_rootpage = "FS" # XXX FS hardcoded

    def run(self):
        """ Perform search and return results object """

        start = time.time()
        hits, estimated_hits = self._search()

        # important - filter deleted pages or pages the user may not read!
        if not self.filtered:
            hits = self._filter(hits)
            logging.debug("after filtering: %d hits" % len(hits))

        return self._get_search_results(hits, start, estimated_hits)

    def _search(self):
        """
        Search pages.

        Return list of tuples (wikiname, page object, attachment,
        matches, revision) and estimated number of search results (If
        there is no estimate, None should be returned).

        The list may contain deleted pages or pages the user may not read.
        """
        raise NotImplementedError()

    def _filter(self, hits):
        """
        Filter out deleted or acl protected pages

        @param hits: list of hits
        """
        userMayRead = self.request.user.may.read
        fs_rootpage = self.fs_rootpage + "/"
        thiswiki = (self.request.cfg.interwikiname, 'Self')
        filtered = [(wikiname, page, attachment, match, rev)
                for wikiname, page, attachment, match, rev in hits
                    if (not wikiname in thiswiki or
                       page.exists() and userMayRead(page.page_name) or
                       page.page_name.startswith(fs_rootpage)) and
                       (not self.mtime or self.mtime <= page.mtime_usecs()/1000000)]
        return filtered

    def _get_search_results(self, hits, start, estimated_hits):
        return getSearchResults(self.request, self.query, hits, start, self.sort, estimated_hits)

    def _get_match(self, page=None, uid=None):
        """
        Get all matches

        XXX xappy highlight functionality should be used for Xapian search!

        @param page: the current page instance
        """
        if page:
            return self.query.search(page)

    def _getHits(self, pages):
        """ Get the hit tuples in pages through _get_match """
        logging.debug("_getHits searching in %d pages ..." % len(pages))
        hits = []
        revisionCache = {}
        fs_rootpage = self.fs_rootpage
        for hit in pages:

            uid = hit.get('uid')
            wikiname = hit['wikiname']
            pagename = hit['pagename']
            attachment = hit['attachment']
            revision = int(hit.get('revision', 0))

            logging.debug("_getHits processing %r %r %d %r" % (wikiname, pagename, revision, attachment))

            if wikiname in (self.request.cfg.interwikiname, 'Self'): # THIS wiki
                page = Page(self.request, pagename, rev=revision)
                if not self.historysearch and revision:
                    revlist = page.getRevList()
                    # revlist can be empty if page was nuked/renamed since it was included in xapian index
                    if not revlist or revlist[0] != revision:
                        # nothing there at all or not the current revision
                        logging.debug("no history search, skipping non-current revision...")
                        continue
                if attachment:
                    # revision currently is 0 ever
                    if pagename == fs_rootpage: # not really an attachment
                        page = Page(self.request, "%s/%s" % (fs_rootpage, attachment))
                        hits.append((wikiname, page, None, None, revision))
                    else:
                        matches = self._get_match(page=None, uid=uid)
                        hits.append((wikiname, page, attachment, matches, revision))
                else:
                    matches = self._get_match(page=page, uid=uid)
                    logging.debug("self._get_match %r" % matches)
                    if matches:
                        if not self.historysearch and \
                                pagename in revisionCache and \
                                revisionCache[pagename][0] < revision:
                            hits.remove(revisionCache[pagename][1])
                            del revisionCache[pagename]
                        hits.append((wikiname, page, attachment, matches, revision))
                        revisionCache[pagename] = (revision, hits[-1])
            else: # other wiki
                hits.append((wikiname, pagename, attachment, None, revision))
        logging.debug("_getHits returning %r." % hits)
        return hits

class MoinSearch(BaseSearch):

    def __init__(self, request, query, sort='weight', mtime=None, historysearch=0, pages=None):
        super(MoinSearch, self).__init__(request, query, sort, mtime, historysearch)

        self.pages = pages

    def _search(self):
        """
        Search pages using moin's built-in full text search

        The list may contain deleted pages or pages the user may not
        read.

        if self.pages is not None, searches in that pages.
        """
        self.request.clock.start('_moinSearch')

        # if self.pages is none, we make a full pagelist, but don't
        # search attachments (thus attachment name = '')
        pages = self.pages or [{'pagename': p, 'attachment': '', 'wikiname': 'Self', } for p in self._getPageList()]

        hits = self._getHits(pages)
        self.request.clock.stop('_moinSearch')

        return hits, None

    def _getPageList(self):
        """ Get list of pages to search in

        If the query has a page filter, use it to filter pages before
        searching. If not, get a unfiltered page list. The filtering
        will happen later on the hits, which is faster with current
        slow storage.
        """
        filter_ = self.query.pageFilter()
        if filter_:
            # There is no need to filter the results again.
            self.filtered = True
            return self.request.rootpage.getPageList(filter=filter_)
        else:
            return self.request.rootpage.getPageList(user='', exists=0)


class XapianSearch(BaseSearch):

    def _xapianIndex(request):
        """ Get the xapian index if possible

        @param request: current request
        """
        try:
            from MoinMoin.search.Xapian import Index
            index = Index(request)
        except ImportError:
            return None

        if index.exists():
            return index

    _xapianIndex = staticmethod(_xapianIndex)

    def _search(self):
        """ Search using Xapian

        Get a list of pages using fast xapian search and
        return moin search in those pages if needed.
        """
        clock = self.request.clock
        pages = None
        index = self._xapianIndex(self.request)

        assert index, 'XXX Assume that index exist, actually we should have thrown an exception, so MoinSearch could be used instead'

        clock.start('_xapianSearch')
        try:
            clock.start('_xapianQuery')
            search_results = index.search(self.query, sort=self.sort, historysearch=self.historysearch)
            clock.stop('_xapianQuery')
            logging.debug("_xapianSearch: finds: %r" % search_results)
            self._xapianIndex = index
        except BaseIndex.LockedException:
            pass

        # XXX must search_results be decoded?

        pages = [{'uid': r.id,
                  'wikiname': r.data['wikiname'][0],
                  'pagename': r.data['pagename'][0],
                  'attachment': r.data['attachment'][0],
                  'revision': r.data.get('revision',[0])[0]}
                 for r in search_results]

        try:
            if not self.query.xapian_need_postproc():
                # xapian handled the full query
                clock.start('_xapianProcess')
                try:
                    _ = self.request.getText
                    return self._getHits(pages), (search_results.estimate_is_exact and '' or _('about'), search_results.matches_estimated)
                finally:
                    clock.stop('_xapianProcess')
        finally:
            clock.stop('_xapianSearch')

        # some postprocessing by _moinSearch is required
        return MoinSearch(self.request, self.query, self.sort, self.mtime, self.historysearch, pages=None)._search()


