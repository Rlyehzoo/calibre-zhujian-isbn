#!/usr/bin/env python


__license__ = "GPL v3"
__copyright__ = "2011, Kovid Goyal <kovid@kovidgoyal.net>; 2011, Li Fanxi <lifanxi@freemindworld.com>"
__docformat__ = "restructuredtext en"

import time

try:
    from queue import Empty, Queue
except ImportError:
    from Queue import Empty, Queue

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Option, Source
from calibre.ebooks.metadata.book.base import Metadata
from calibre import as_unicode

NAMESPACES = {
    "openSearch": "http://a9.com/-/spec/opensearchrss/1.0/",
    "atom": "http://www.w3.org/2005/Atom",
    "db": "https://www.douban.com/xmlns/",
    "gd": "http://schemas.google.com/g/2005",
}


class zhujian(Source):

    name = "Zhujian isbn"
    author = "Rlyehzoo"
    version = (1, 0, 0)
    minimum_calibre_version = (1, 0, 0)

    description = _(
        "metadata download based on https://github.com/qiaohaoforever/DoubanBook"
        "Useful only for Chinese language books."
    )

    capabilities = frozenset(["identify", "cover"])
    touched_fields = frozenset(
        [
            "title",
            "authors",
            "pubdate",
            "comments",
            "publisher",
            "identifier:isbn",
            "rating",
            "identifier:douban",
        ]
    )  # language currently disabled
    supports_gzip_transfer_encoding = True
    cached_cover_url_is_reliable = True

    DOUBAN_API_URL = "https://api.douban.com/v2/book/search"
    DOUBAN_BOOK_URL = "https://book.douban.com/subject/%s/"

    options = (
        Option(
            "include_subtitle_in_title",
            "bool",
            True,
            _("Include subtitle in book title:"),
            _("Whether to append subtitle in the book title."),
        ),
        Option(
            "apikey", "string", "", _("zhujian api apikey"), _("zhujian api apikey")
        ),
    )

    def to_metadata(self, browser, log, entry_, timeout):  # {{{
        from calibre.utils.date import parse_date, utcnow
        import re

        douban_url = entry_.get("url")
        douban_id = str(re.search("\d+",douban_url).group())
        title = entry_.get("title")
        description = entry_.get("book_intro")
        # subtitle = entry_.get('subtitle')  # TODO: std metada doesn't have this field
        isbn = entry_.get("isbn")  # ISBN11 is obsolute, use ISBN13
        cover_url = entry_.get("cover_url")
        publisher = None
        pubdate = None
        authors = None
        if "book_info" in entry_:
            book_info = entry_["book_info"]
            publisher = book_info["出版社"]
            pubdate = book_info["出版年"]
            authors = book_info["作者"]
        elif "abstract" in entry_:
            book_info = entry_["abstract"]
            info = book_info.split('/')
            authors = info[0:-3].trim()
            pubdate = info[-1].trim()
            publisher = info[-2].trim()
        
        rating = None
        if "rating" in entry_:
            doubanrating = entry_["rating"]
            rating = doubanrating["value"]


        if not authors:
            authors = [_("Unknown")]
        else:
            authors=[authors]
        if not douban_id or not title:
            # Silently discard this entry
            return None

        mi = Metadata(title, authors)
        mi.identifiers = {"douban": douban_id}
        mi.publisher = publisher
        mi.comments = description
        # mi.subtitle = subtitle

        # ISBN
        isbns = []
        if isinstance(isbn, (type(""), bytes)):
            if check_isbn(isbn):
                isbns.append(isbn)
        else:
            for x in isbn:
                if check_isbn(x):
                    isbns.append(x)
        if isbns:
            mi.isbn = sorted(isbns, key=len)[-1]
        mi.all_isbns = isbns

        # pubdate
        if pubdate:
            try:
                default = utcnow().replace(day=15)
                mi.pubdate = parse_date(pubdate, assume_utc=True, default=default)
            except:
                log.error("Failed to parse pubdate %r" % pubdate)

        # Ratings
        if rating:
            try:
                mi.rating = rating / 2.0
            except:
                log.exception("Failed to parse rating")
                mi.rating = 0

        # Cover
        mi.has_douban_cover = None
        u = cover_url
        if u:
            # If URL contains "book-default", the book doesn't have a cover
            if u.find("book-default") == -1:
                mi.has_douban_cover = u

        return mi

    # }}}

    def get_book_url(self, identifiers):  # {{{
        db = identifiers.get("douban", None)
        if db is not None:
            return ("douban", db, self.DOUBAN_BOOK_URL % db)

    # }}}

    def create_query(self, log, title=None, authors=None, identifiers={}):  # {{{
        try:
            from urllib.parse import urlencode
        except ImportError:
            from urllib import urlencode
        ISBN_URL = "https://api.feelyou.top/isbn/"

        q = ""
        t = None
        isbn = check_isbn(identifiers.get("isbn", None))
        subject = identifiers.get("douban", None)
        if isbn is not None:
            q = isbn
            t = "isbn"
        else :
            log.error("no isbn")


            def build_term(prefix, parts):
                return " ".join(x for x in parts)

            title_tokens = list(self.get_title_tokens(title))
            if title_tokens:
                q += build_term("title", title_tokens)
            author_tokens = list(
                self.get_author_tokens(authors, only_first_author=True)
            )
            if author_tokens:
                q += (" " if q != "" else "") + build_term("author", author_tokens)
            t = "search"
        q = q.strip()
        # if isinstance(q, type("")):
        #    q = q.encode("utf-8")
        q = str(q)
        if not q:
            return None
        url = None
        if t == "isbn":
            url = ISBN_URL + q
        #if self.prefs.get("apikey"):
        #    if t == "isbn" or t == "subject":
        #        url = url + "?apikey=" + self.prefs["apikey"]
        #    else:
        #        url = url + "&apikey=" + self.prefs["apikey"]
        return url

    # }}}

    def download_cover(
        self,
        log,
        result_queue,
        abort,  # {{{
        title=None,
        authors=None,
        identifiers={},
        timeout=30,
        get_best_cover=False,
    ):
        cached_url = self.get_cached_cover_url(identifiers)
        if cached_url is None:
            log.info("No cached cover found, running identify")
            rq = Queue()
            self.identify(
                log, rq, abort, title=title, authors=authors, identifiers=identifiers
            )
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(
                key=self.identify_results_keygen(
                    title=title, authors=authors, identifiers=identifiers
                )
            )
            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
        if cached_url is None:
            log.info("No cover found")
            return

        if abort.is_set():
            return
        br = self.browser
        log("Downloading cover from:", cached_url)
        try:
            cdata = br.open_novisit(cached_url, timeout=timeout).read()
            if cdata:
                result_queue.put((self, cdata))
        except:
            log.exception("Failed to download cover from:", cached_url)

    # }}}

    def get_cached_cover_url(self, identifiers):  # {{{
        url = None
        db = identifiers.get("douban", None)
        if db is None:
            isbn = identifiers.get("isbn", None)
            if isbn is not None:
                db = self.cached_isbn_to_identifier(isbn)
        if db is not None:
            url = self.cached_identifier_to_cover_url(db)

        return url

    # }}}

    def get_all_details(self, br, log, entries, abort, result_queue, timeout):  # {{{
        try:
            ans = self.to_metadata(br, log, entries, timeout)
            if isinstance(ans, Metadata):
                ans.source_relevance = 0
                db = ans.identifiers["douban"]
                for isbn in getattr(ans, "all_isbns", []):
                    self.cache_isbn_to_identifier(isbn, db)
                if ans.has_douban_cover:
                    self.cache_identifier_to_cover_url(db, ans.has_douban_cover)
                self.clean_downloaded_metadata(ans)
                result_queue.put(ans)
        except:
            log.exception("Failed to get metadata for identify entry:", entries)

    # }}}

    def identify(
        self,
        log,
        result_queue,
        abort,
        title=None,
        authors=None,  # {{{
        identifiers={},
        timeout=30,
    ):

        # check apikey
        if not self.prefs.get("apikey"):
            return

        import json

        query = self.create_query(
            log, title=title, authors=authors, identifiers=identifiers
        )
        if not query:
            log.error("Insufficient metadata to construct query")
            return
        br = self.browser
        br.addheaders = [
            ('apikey', self.prefs["apikey"]),
        ]
        log('apikey is ',self.prefs["apikey"])
        try:
            raw = br.open_novisit(query, timeout=timeout).read()
        except Exception as e:
            log.exception("Failed to make identify query: %r" % query)
            return as_unicode(e)
        try:
            j = json.loads(raw)
        except Exception as e:
            log.exception("Failed to parse identify results")
            return as_unicode(e)
        if j is not None:
            entries = j
        else:
            entries = []
            entries.append(j)
        if not entries and identifiers and title and authors and not abort.is_set():
            return self.identify(
                log, result_queue, abort, title=title, authors=authors, timeout=timeout
            )
        # There is no point running these queries in threads as douban
        # throttles requests returning 403 Forbidden errors
        self.get_all_details(br, log, entries, abort, result_queue, timeout)

        return None

    # }}}


if __name__ == "__main__":  # tests {{{
    # To run these test use: calibre-debug -e src/calibre/ebooks/metadata/sources/douban.py
    from calibre.ebooks.metadata.sources.test import (
        test_identify_plugin,
        title_test,
        authors_test,
    )

    test_identify_plugin(
        zhujian.name,
        [
            (
                {
                    "identifiers": {"isbn": "9787506380263"},
                },
                [title_test("人间失格", exact=True), authors_test(["太宰治"])],
            )
        ],
    )
# }}}
