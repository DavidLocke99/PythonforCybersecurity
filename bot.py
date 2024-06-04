"""
categories.py - Sopel Categories plugin
Copyright 2023 Morris_@micasa.chat
Licensed under the Eiffel Forum License 2.

https://sopel.chat
"""

from __future__ import annotations

import collections
import csv
import datetime
import json
import urllib.parse

import httplib2
import io
import logging
import os
import random
import re
import threading
from urllib import parse

import sopel.trigger
from sopel import config
from sopel import formatting
from sopel import plugin
from sopel import plugins
from sopel import tools
from sopel import trigger
from sopel.config import types
from sopel.config.types import ValidatedAttribute


LOGGER = sopel.tools.get_logger('categories')
PLUGIN_OUTPUT_PREFIX = '[categories] '
VERSION_STAMP = '1.3.10 (2024/06/01 22:00:00)'

""" plugin interval for periodic call back"""
PLUGIN_INTERVAL: int = 1

V_VERYQUIET = 1
V_QUIET = 2
V_NORMAL = 3
V_CHATTY = 4
V_VERYCHATTY = 5

class CategoriesSection(config.types.StaticSection):
    """ This is the config section for the categories plugin
    max_categories: int: this is a soft limit on the maximum number of categories for an image
    default_rounds: int: the number of rounds for game play
    default_delay: int: how long (in seconds) should an image be posted before the round ends
    default_pause: int: how long to wait after a round before starting a new round
    """
    max_categories: ValidatedAttribute = types.ValidatedAttribute('max_categories', int, default=2000)
    default_rounds: ValidatedAttribute = types.ValidatedAttribute('default_rounds', int, default=5)
    default_delay: ValidatedAttribute = types.ValidatedAttribute('default_delay', int, default=60)
    default_pause: ValidatedAttribute = types.ValidatedAttribute('default_pause', int, default=15)
    enabled_commands: ValidatedAttribute = types.ValidatedAttribute('enabled_commands', int, default=1)
    idle_time: ValidatedAttribute = types.ValidatedAttribute('idle_time', int, default=0)

class CategoryDictionary(dict[int, str]):
    """ This dictionary class maps category strings to category ids
    The purpose of this class is to organize the player keywords for images and allow us to pull images
    from the image directory with category keywords.  This is a mapping of ids to category keywords. The
    image directory contains the categories picked by players and the count of times the category was chosen
    in game play for this image.
    """
    def __init__(self, categories_file_: str):
        """ initialize the mapping of ids to all categories
        :param categories_file_: this is the path to the CSV file used to persist the categories
        :type categories_file_: str
        """
        super().__init__(self)
        self.lock = threading.Lock()
        self.next_index: int = 1
        self.categories_file: str = categories_file_
        self.reverse_lookup: dict[str, int] = {}

    def __missing__(self, key: int) -> str:
        """ __missing__ override to return null strin as the result,
         meaning the category doesn't exist, this overrides the dictionary class method
        """
        return str('')

    def read_categories(self) -> bool:
        """ read the mapping of ids to category strings
        The CSV file contains the image id in the first column and the url in the second.
        the remaining fields are pairs of (category id, count) for this image.  This defines
        the player preferences for the image.
        :param categories_file_: file name of CSV (space delimited) of id category string to id
        :type categories_file_: str
        """
        with self.lock:
            idx: int = self.next_index
            with io.open( self.categories_file, 'r', newline='', encoding="utf-8") as f_cats:
                category_reader = csv.reader(f_cats, delimiter=' ')
                for row in category_reader:
                    id_: int = int(row[0])
                    if id_ > idx:
                        idx = id_
                    self[id_] = parse.unquote_plus(row[1])
                    self.reverse_lookup[parse.unquote_plus(row[1])] = id_
            read_file = idx > self.next_index
            self.next_index = idx
        return read_file

    def update_category(self, key: int):
        """ update the CSV category file with one new category
        This method appends a line to the category file, we add new categories at the end,
        this should be faster that writing the entire file on a checkpoint call.
        """
        with self.lock:
            with io.open(self.categories_file, 'a', newline='', encoding="utf-8") as f_cats:
                row: list[str] = []
                updater = csv.writer(f_cats, delimiter=' ')
                row.append(str(key))
                row.append(parse.quote_plus(self[key]))
                updater.writerow(row)

    def checkpoint(self):
        """ checkpoint the CSV file
        Write the entire categories out to the category CSV file for this channel.
        This is for paranoia, if the bot crashes, we shouldn't have lost much information
        """
        with self.lock:
            with io.open(self.categories_file, 'w', newline='', encoding="utf-8") as f_cats:
                row: list[str] = []
                updater = csv.writer(f_cats, delimiter=' ')
                for key in self.keys():
                    row.clear()
                    row.append(str(key))
                    row.append(parse.quote_plus(self[key]))
                    updater.writerow(row)
        return

    def get_index(self, item_: str) -> int:
        """ Return the index for the item item_
        This routine may want to be improved to match similar items so we don't get too lost in the weeds,
        for new we just use the reverse lookup.
        :param item_: this is a category item may not yet be in the dictionary
        :type item_: str
        :return index of item, or zero if not found
        """
        with self.lock:
            id_:int = 0
            cat_: str = parse.unquote_plus(item_.casefold())
            if cat_ in self.reverse_lookup:
                return self.reverse_lookup[cat_]
        return 0

    def has_category(self, key_: int)-> bool:
        """ return True if this key is in the dictionary
        This method is used to differentiate between adding a new key vs accessing a pre-exising key
        :param key_: key to category to test
        :type key_: int
        """
        with self.lock:
            return key_ in self

    def add_category(self, cat_: str)-> int:
        """ add a category to the dictionary
        This method will add a casefolded keyword to the category dictionary and add the complement
        to the reverse_lookup dictionary.  This eliminates the need to create the reverse lookup
        on each call.
        :param cat_: this is a string to be added to the dictionary, it can be a word or phrase
        :type cat_: str
        """
        # check for a match first and return the index of the match
        category_: str = parse.unquote_plus(cat_.rstrip().lstrip().casefold())
        idx: int = self.get_index(category_)
        if idx != 0:
            return idx
        else:
            # get the keys and find the highest value, this will change as categories get deleted
            # update the the dictionary and the reverse lookup dictionary as well
            with self.lock:
                #sorted_keys: list[int] = sorted(self.keys())
                # next_index is set to 1 greater than the current max index
                #idx: int = sorted_keys[len(sorted_keys)-1] + 1
                if len(self.keys()):
                    idx = max(self.keys()) + 1
                else:
                    idx = 1
                self[idx] = parse.unquote_plus(category_)
                self.reverse_lookup[parse.unquote_plus(category_)] = idx
            self.update_category(idx)
            return idx

    def delete_category(self, key_: int):
        """ delete a category and remove it from the CSV file
        :param key_: key to category to remove
        :type key_: int
        """
        do_checkpoint: bool = False
        with self.lock:
            if key_ in self:
                # keywords are unique so the reverse lookup is a 1:1 mapping as well
                # this saves time when we need to lookup by keyword
                keyword = self[key_]
                del self[key_]
                del self.reverse_lookup[keyword]
                do_checkpoint = True
        if do_checkpoint:
            self.checkpoint()

    def fetch_keywords(self) -> list[ str]:
        keywords: list[str] = []
        for key,value in self.items():
            if value not in keywords:
                keywords.append(value)
        return keywords


    def find_matches(self, keyword: str) -> list[int]:
        """ fuzzy match of keyword to category IDs"""
        matches: list[int] = []
        for key,value in self.items():
            if keyword in value:
                matches.append(key)
        return matches

    def find_matches_exact(self, keyword: str) -> list[int]:
        """ fuzzy match of keyword to category IDs"""
        matches: list[int] = []
        for key, value in self.items():
            if keyword == value:
                matches.append(key)
        return matches

    def find_duplicates(self):
        all_kws: dict[str,list[int]] = {}
        # find duplicates
        for id in self.keys():
            kw: str = self[id]
            if kw not in all_kws:
                ids: list[int] = []
                ids.append(id)
                all_kws[kw] = ids
            else:
                all_kws[kw].append(id)
        all_keys = list(all_kws.keys())
        all_keys.sort()

        #build replacement id list for images
        repl_ids: dict[int, int] = {}
        for kw in all_keys:
            if len(all_kws[kw]) > 1:
                id_list = all_kws[kw];
                default_id = id_list.pop()
                while len(id_list):
                    repl_id = id_list.pop()
                    repl_ids[repl_id] = default_id
                    del self[repl_id]
        if len(repl_ids):
            self.checkpoint()
        return repl_ids


class Categories(dict[int, int]):
    """ class to contain the category id and the count of votes
    This class collects the cumulative votes for the image it is associated with.
    As the image is played in the game, additional categories may be added and exisiting one
    have the vote totals incremented. The dictionary is appened after the image URL in pairs of
    ints, first is category id, second is the count of 'love' for this category for this image.
    """
    def __init__(self):
        """ A category is a word or short phrase that players use to describe an image
        """
        super().__init__(self)

    def __missing__(self, key: int) -> int:
        # base dict class override, return 0, an invalid category
        return 0

    def add_category(self, category_: int, count_: int) -> bool:
        """ add this category to the image, at this point the category exists in the
        category dictionary, so the category id is legit
        :param category_: add a category id to the Categories dictionary for an image
        :type category_: int
        :param count_: add this count_ to the category_
        :type count_: int
        :return: bool
        """
        exists: bool = (self.get(category_) != 0)
        if exists:
            self[category_] += count_
        else:
            self[category_] = count_
        return exists

    def del_category(self, category_: int) -> bool:
        """ add this category to the image, at this point the category exists in the
        category dictionary, so the category id is legit
        :param category_: add a category id to the Categories dictionary for an image
        :type category_: int
        :return: bool
        """
        exists: bool = (self.get(category_) != 0)
        if exists:
            del self[category_]
        return exists


class Image:
    """ the Image class represents the image id, url and category data
    This collects all the information about one image, it's ID, the url and
    the dictionary of category keywords and counts. This category information
    will be used to classify the image.
    """
    def __init__(self, link_: int, url_: str, categories_: Categories):
        """
        Initialize and image
        :param link_: link id for this image
        :type link_: int
        :param url_: this image URL for this image
        :type url_: str
        :param categories_:  dictionary of categories and vote totals for this image
        :type categories_: Catagories
        """
        self.link_key: int = link_
        self.url: str = url_
        self.categories: Categories = categories_

    def has_category(self, key_: int) -> bool:
        """ check if the category is in the image dictionary
        :param key_: the category key (id)
        :type key_: int
        """
        return key_ in self.categories

    def add_category(self, key_: int, count_: int) -> int:
        """ cadd the category to the image's category dictionary
        :param key_: the category key (id)
        :type key_: int
        :param count_: the count of player loves
        :type count_: int
        """
        if self.has_category(key_):
            self.categories[key_] += count_
        else:
            self.categories[key_] = count_
        return self.categories[key_]

    def del_category(self, key_: int) -> bool:
        return self.categories.del_category(key_)

    def get_url(self) -> str:
        """ return the image url """
        return self.url

    def set_url(self, url: str) -> str:
        """ set the url and return it"""
        self.url = url
        return self.url

    def get_id(self) -> int:
        return self.link_key

    def set_id(self, id_: int) -> int:
        self.link_key = id_
        return self.link_key

    def get_categories(self) -> Categories:
        return self.categories

    def set_categories(self, categories: Categories):
        self.categories = categories

    def serialize(self) -> list[str]:
        """ serialize the Image into a row of values to be stored in the CSV file
        This utility method returns a list of strings, each item will be in a column
        in the csv file, first is the id, then url, the pairs of (id,count) for the categories
        """
        row: list[str] = []
        row.append(str(self.link_key))
        row.append(str(self.url))
        row_item: int = 2
        for key in self.categories.keys():
            row.append(str(key))
            row.append(str(self.categories.get(key)))
            row_item += 2
        return row


class ImageDictionary(dict):
    """ The Image dictionary contains the set of images and the associated categories

    """
    def __init__(self, url_file_: str, deleted_url_file_: str):
        super().__init__(self)
        self.lock = threading.Lock()
        self.next_image_id: int = 1
        self.url_file: str = url_file_
        self.deleted_url_file: str = deleted_url_file_

    def __missing__(self, key):
        return None

    def read_images(self) -> int:
        """ read the rows of the CSV file, into images.
        """
        dups: int = 0
        with self.lock:
            url_map: dict[str,int] = {}
            with io.open(self.url_file, 'r', newline='', encoding="utf-8") as f_images:
                url_reader = csv.reader(f_images, delimiter=' ')
                for row in url_reader:
                    id_: int = int(row[0])
                    url_: str = row[1]
                    if url_ not in url_map:
                        url_map[url_] = id_
                        if id_ > self.next_image_id:
                            self.next_image_id = id_
                        cats_: list[int]= list(range(2, len(row),2))
                        image_cats_: Categories = Categories()
                        for idx in cats_:
                            cat_idx = int(row[idx])
                            cat_cnt = int(row[idx+1])
                            image_cats_.add_category(cat_idx, cat_cnt)
                        self[id_] = Image(id_, url_, image_cats_)
                    else:
                        cats_: list[int]= list(range(2, len(row),2))
                        id_: int = url_map[url_]
                        image = self[id_]
                        for idx in cats_:
                            cat_idx = int(row[idx])
                            cat_cnt = int(row[idx+1])
                            image.add_category(cat_idx, cat_cnt)
                        self[id_] = image
                        dups += 1
                self.next_image_id += 1
                
        if dups:
            self.renumber_images()
            
        return len(self.keys())

    def renumber_images(self)-> int:
        """
        renumber all images sequentially
        :return: number of images
        """
        have_images: int = 0
        with self.lock:
            new_id: int = 1
            sorted_keys: list[int] = sorted(self.keys())
            images: list[ Image ] = []
            for key in sorted_keys:
                image: Image = self.get(key)
                image.set_id(new_id)
                images.append(image)
                new_id += 1;
            self.next_image_id = new_id
            self.clear()
            for image in images:
                self[image.get_id()] = image;
            # checkpoint here, holding the lock
            with io.open(self.url_file, 'w', newline='', encoding="utf-8") as f_cats:
                image_writer = csv.writer(f_cats, delimiter=' ')
                for id in sorted_keys:
                    image: Image = self.get(id)
                    if image:
                        row: list[str] = image.serialize()
                        image_writer.writerow(row)
        return len(self.keys())


    def find_image(self, url_: str):
        with self.lock:
            for (key, image) in self.items():
                if url_ in image.get_url():
                    return key
        return 0

    def add_image(self, url_: str) -> int:
        """ add an image to the image dictionary, this will check point the image dictionary """
        id_: int = 0
        with self.lock:
            id_ = self.next_image_id
            self.next_image_id += 1
            self[id_] = Image(id_, url_, Categories())
            self.append_image(id_)
        return id_

    def delete_image(self, id_: int) -> bool:
        """ remove an image from the dictionary
        """
        deleted: bool = False
        with self.lock:
            if id_ in self:
                deleted = True
            if deleted:
                image_ : Image = self[id_]
                del self[id_]
                row: list[str] = image_.serialize()
                LOGGER.info('recording delete of image {0} into file {1}'.format(id_, self.deleted_url_file))
                with io.open(self.deleted_url_file, 'a', newline='', encoding="utf-8") as f_images:
                    updater = csv.writer(f_images, delimiter=' ')
                    updater.writerow(row)
        # checkpoint() will also acquire the lock,
        if deleted:
            self.checkpoint()
        return deleted

    def get_url(self, id_: int) -> str:
        image_: Image = self[id_]
        if image_:
            return image_.get_url()
        else:
            return str('')

    def get_image(self, id_: int) -> Image:
        if id_ in self:
            return self[id_]
        else:
            return None

    def set_image(self, image_: Image) -> bool:
        if image_.get_id() in self:
            self[image_.get_id()] = image_
            return True
        else:
            return False

    def append_image(self, id_: int) -> bool:
        if id_ not in self:
            return False
        image: Image = self[id_]
        if image:
            row: list[str] = image.serialize()
            with io.open(self.url_file, 'a', newline='', encoding="utf-8") as f_images:
                updater = csv.writer(f_images, delimiter=' ')
                updater.writerow(row)
            return True
        else:
            return False

    def fetch_deleted_ids(self)-> list[int]:
        """ return a list of id's that have been deleted """
        deleted_ids: list[int] = []
        if os.path.exists(self.deleted_url_file):
            with self.lock:
                with io.open(self.deleted_url_file, 'r', newline='', encoding="utf-8") as f_images:
                    url_reader = csv.reader(f_images, delimiter=' ')
                    for row in url_reader:
                        id_: int = int(row[0])
                        deleted_ids.append(id_)
            deleted_ids.sort()
        return deleted_ids;

    def fetch_deleted_url(self, id_: int) -> str:
        """ fetch the URL for a deleted image id """
        url_: str = "id not found in deleted images"
        if os.path.exists(self.deleted_url_file):
            with self.lock:
                with io.open(self.deleted_url_file, 'r', newline='', encoding="utf-8") as f_images:
                    url_reader = csv.reader(f_images, delimiter=' ')
                    for row in url_reader:
                        if id_ == int(row[0]):
                            url_: str = row[1]
                            break
        return url_

    def restore_image(self, id_: int) -> int:
        """ restore an image from the deleted_images.csv back to the the images_csv for this channel
        """
        restored: bool = False
        restored_id: int = -1
        rows: list[list[str]] = []
        if os.path.exists(self.deleted_url_file):
            with self.lock:
                with io.open(self.deleted_url_file, 'r', newline='', encoding="utf-8") as f_images:
                    url_reader = csv.reader(f_images, delimiter=' ')
                    for row in url_reader:
                        if id_ == int(row[0]):
                            url_: str = row[1]
                            cats_: list[int]= list(range(2, len(row),2))
                            image_cats_: Categories = Categories()
                            for idx in cats_:
                                cat_idx = int(row[idx])
                                cat_cnt = int(row[idx+1])
                                image_cats_.add_category(cat_idx, cat_cnt)
                            # create the imagte and make it current
                            image: Image = Image(id_, url_, image_cats_)
                            if id_ not in self:
                                self[id_] = image
                            else:
                                id_ = self.next_image_id
                                self.next_image_id += 1
                                image.set_id(id_)
                                self[id_] = Image(id_, url_, Categories())
                                self.append_image(id_)
                            restored_id = id_
                            restored = True
                        else:
                            # this entry needs to stay int he deleted files.
                            rows.append(row)

                # write the rows back out to the file
                rows.sort(key=lambda x: int(x[0]))
                with io.open(self.deleted_url_file , 'w', newline='', encoding="utf-8") as f_images:
                    url_writer = csv.writer(f_images, delimiter=' ')
                    for row in rows:
                        url_writer.writerow(row)
        return restored_id

    def checkpoint(self) -> bool:
        """checkpoint the file
        :return: True if checkpoint was successful
        """
        have_images: int = 0
        with self.lock:
            sorted_keys: list[int] = sorted(self.keys())
            have_images = len(sorted_keys)
            with io.open(self.url_file, 'w', newline='', encoding="utf-8") as f_images:
                image_writer = csv.writer(f_images, delimiter=' ')
                for id in sorted_keys:
                    image: Image = self.get(id)
                    if image:
                        row: list[str] = image.serialize()
                        image_writer.writerow(row)
        return have_images > 0

    def find_matches(self, cats: list[int]) -> list[int]:
        """
        :param cats:
        :return:
        """
        image_keys: list[int] = []
        if len(cats) > 0:
            for key,image in self.items():
                for cat in cats:
                    if image.has_category(cat):
                        image_keys.append(key)
                        break
        return image_keys
    
    def set_prefix(self,src:str,dest:str):
        """

        :param src: leading part of file reference to be replaced
        :param dest: leading part of URL to set for web access
        :return:
        """
        for key,image in self.items():
            url: str = image.get_url()
            url = url.replace(src,dest)
            image.set_url(url)
            self[key] = image

    def remove_duplicate_categories(self, replacements: dict[int,int]) -> bool:
        need_checkpoint: bool = False
        for image_id in self.keys():
            image = self[image_id]
            categories = image.get_categories()
            updated_cats = categories;
            catids = list(categories.keys())
            repids = list(replacements.keys())
            updated_image = False
            for id in catids:
                if id in repids:
                    count = categories[id]
                    if replacements[id] in catids:
                        updated_cats[replacements[id]] += count
                    else:
                        updated_cats[replacements[id]] = count
                    del updated_cats[id]
                    updated_image = True;
                else:
                    updated_cats[id] = categories[id]
            if updated_image:
                image.set_categories(updated_cats)
                self[image_id] = image;
                need_checkpoint = True
            if need_checkpoint:
                self.checkpoint()
        return need_checkpoint

    def remove_duplicate_deleted_image_categories(self, replacements: dict[int, int]) -> bool:
        need_checkpoint: bool = False
        if os.path.exists(self.deleted_url_file):
            img_dict: dict[int,Image] = {}
            with self.lock:
                # read deleted images
                with io.open(self.deleted_url_file, 'r', newline='', encoding="utf-8") as f_images:
                    url_reader = csv.reader(f_images, delimiter=' ')
                    for row in url_reader:
                        id_ = int(row[0])
                        url_: str = row[1]
                        cats_: list[int]= list(range(2, len(row),2))
                        image_cats_: Categories = Categories()
                        for idx in cats_:
                            cat_idx = int(row[idx])
                            cat_cnt = int(row[idx+1])
                            image_cats_.add_category(cat_idx, cat_cnt)
                        # create the imagte and make it current
                        image: Image = Image(id_, url_, image_cats_)
                        img_dict[id_] = image

                # remove replicated keys
                for image_id in img_dict.keys():
                    image = img_dict[image_id]
                    categories = image.get_categories()
                    updated_cats = categories;
                    catids = list(categories.keys())
                    repids = list(replacements.keys())
                    updated_image = False
                    for id in catids:
                        if id in repids:
                            count = categories[id]
                            if replacements[id] in catids:
                                updated_cats[replacements[id]] += count
                            else:
                                updated_cats[replacements[id]] = count
                            del updated_cats[id]
                            updated_image = True;
                        else:
                            updated_cats[id] = categories[id]
                        if updated_image:
                            image.set_categories(updated_cats)
                            self[image_id] = image;
                            need_checkpoint = True

                # write out new deleted images
                if need_checkpoint:
                    sorted_images:list[int] = list(img_dict.keys())
                    sorted_images.sort()
                    with io.open(self.deleted_url_file, 'w', newline='', encoding="utf-8") as f_images:
                        url_writer = csv.writer(f_images, delimiter=' ')
                        for image_id in sorted_images:
                            row: list[str] = img_dict[image_id].serialize()
                            url_writer.writerow(row)
        # return status
        return need_checkpoint


class Autoplay():
    """ this class handles the periodic callback from sopel """
    def __init__(self):
        self.autoplay: bool = False
        self.delay_: int = 30
        self.sequential_: bool = False
        self.start_id = -1
        self.count_: int = 0
        self.cur_id_: int = 0
        self.image_keys: list[int] = []

    def toggle_autoplay(self):
        if self.autoplay:
            self.autoplay = False
        else:
            self.autoplay = True
        return

    def get_autoplay_state(self) -> bool:
        return self.autoplay

    def set_autoplay(self, state_: bool, delay_ = 30, sequential_: bool = False,
                     count_up_: bool = True, loop_ : bool = False, image_keys: list[int] = []):
        self.autoplay = state_
        self.delay_ = delay_
        self.sequential_ = sequential_
        self.loop_ = loop_
        self.count_up_ = count_up_
        self.count_ = 0
        self.cur_id_ = 0
        self.image_keys.clear()
        if len(image_keys):
            self.image_keys = image_keys.copy()
            if not self.count_up_:
                self.cur_id_ = len(self.image_keys)
            self.count_ = self.delay_

    def has_image_keys(self) -> bool:
        return len(self.image_keys) > 0

    def show_next_image(self) -> bool:
        self.count_ +=1
        if self.count_ >= self.delay_:
            self.count_ = 0
            return True
        else:
            return False

    def fetch_next_id(self) -> int:
        cur_id: int = 0
        if self.sequential_:
            if self.count_up_:
                cur_id = self.image_keys[self.cur_id_]
                self.cur_id_ += 1
                if self.cur_id_ >= len(self.image_keys):
                    if self.loop_:
                        self.cur_id_ = 0
                    else:
                        self.set_autoplay(False)
                        return -1
            else:
                self.cur_id_ -= 1
                if self.cur_id_ < 0:
                    if self.loop_:
                        self.cur_id_ = len(self.image_keys) - 1
                    else:
                        self.set_autoplay(False)
                        return -1;
                cur_id = self.image_keys[self.cur_id_]
        else:
            cur_id = random.choice(self.image_keys)
        return cur_id


class ScorePoints():
    """ points awarded per event """
    def __init__(self):
        self.CreatePoints = 15
        self.FirstMatchPoints = 10
        self.SecondMatchPoints = 5
        self.ThirdMatchPoints = 2

    def create_points(self):
        return self.CreatePoints

    def first_points(self):
        return self.FirstMatchPoints

    def second_points(self):
        return self.SecondMatchPoints

    def third_points(self):
        return self.ThirdMatchPoints


score_points = ScorePoints()

class Scorecard():
    """
    this class keeps track of the scores for the game
    """
    def __init__(self):
        self.nick: str = ""
        self.score = 0
        self.create_cat_count: int = 0
        self.first_match_count: int = 0
        self.second_match_count: int = 0
        self.third_match_count: int = 0
        self.image_loves: dict[ int, list[str]] = {}

    def icrement_creates(self):
        self.create_cat_count += 1

    def incremet_firsts(self):
        self.first_match_count += 1

    def increment_seconds(self):
        self.second_match_count += 1

    def increment_thirds(self):
        self.third_match_count += 1

    def update_loves(self, image_id_: int, loves: list[str]):
        clean_loves: list[str] = []
        for love in loves:
            clean_loves.append(love.lstrip().rstrip())
        if image_id_ not in self.image_loves:
            self.image_loves[image_id_] = clean_loves
        else:
            image_loves = self.image_loves[image_id_]
            for one_love in clean_loves:
                image_loves.append(one_love)
            self.image_loves[image_id_] = image_loves

    def update_scores(self, channel_key_: str, image_id_: int)-> int:
        val_dict: dict[ int, list[int]] = {}
        image: Image = channel_data[channel_key_].image_dictionary[image_id_]
        if image is None:
            return 0
        sorted_cats: list[(int,int)] = sorted(image.categories.items(), key=lambda x:x[1],reverse=True)
        id_1 = -1
        id_2 = -2
        id_3 = -3
        if len(sorted_cats):
            v,id_1 = sorted_cats.pop(0)
        if len(sorted_cats):
            v,id_2 = sorted_cats.pop(0)
        if len(sorted_cats):
            v,id_3 = sorted_cats.pop(0)
        if image_id_ in self.image_loves:
            loves = self.image_loves[image_id_]
            for love in loves:
                id = channel_data[channel_key_].category_dictionary.get_index(love)
                if id == id_1:
                    self.incremet_firsts()
                if id == id_2:
                    self.increment_seconds()
                if id == id_3:
                    self.increment_thirds()
        return self.compute_score()

    def compute_score(self) -> int:
        score: int = 0
        score += self.create_cat_count * score_points.create_points()
        score += self.first_match_count * score_points.first_points()
        score += self.second_match_count * score_points.second_points()
        score += self.third_match_count * score_points.third_points()
        self.score = score
        return score


class GamePlay:
    """
    this is the class that will collect the Game data per channel
    """
    def __init__(self, default_rounds: int, default_delay: int, default_pause: int ):
        self.closed: bool = True
        self.game_on: bool = False
        self.autogame: bool = False
        self.delay: int = default_delay
        self.rounds: int = default_rounds
        self.pause: int = default_pause
        self.current_image_id: int = 0
        self.current_round = 0
        self.current_pause = 0
        self.current_delay = 0
        self.players: dict[ str, Scorecard ] = {}
        self.mutex: threading.Lock = threading.Lock()

    def is_closed(self) -> bool:
        return self.closed

    def is_opened(self) -> bool:
        return not self.is_closed()

    def set_closed(self, new_state: bool):
        self.closed = new_state

    def get_game_state(self) -> bool:
        return self.game_on

    def get_game_mode(self) -> bool:
        return self.autogame and self.game_on

    def auto_start(self, rounds: int, delay: int, pause: int):
        self.rounds = rounds
        self.delay = delay
        self.pause = pause
        self.current_image_id = 0
        self.current_round = 0
        self.current_pause = 0
        self.current_delay = 0
        self.autogame = True
        self.game_on = True

    def next_round(self):
        pass

    def process_clocktick(self, bot: sopel.bot.SopelWrapper, channel_key_: str):
        with self.mutex:
            channel_ = channel_data[channel_key_]

            pause_remaining = self.pause - self.current_pause
            if pause_remaining == self.pause:
                self.current_round += 1
                time_remaining = formatting.color(formatting.bold('{0}'.format(pause_remaining)), formatting.colors.BLUE)
                bot.say('{0}: round {1} starting in {2} seconds'
                        .format('[game,auto]', self.current_round, time_remaining), channel_.get_channel_name())
            if pause_remaining > 0:
                self.current_pause += 1
                if pause_remaining < 4:
                    time_remaining = formatting.color(formatting.bold('{0}'.format(pause_remaining)), formatting.colors.RED)
                    bot.say("{2}: round {0} starting in {1} seconds"
                            .format(self.current_round, time_remaining, '[game,auto]'),
                            channel_.get_channel_name())
                if pause_remaining == 1:
                    keys: list[int] = list(channel_.image_dictionary)
                    num = 0

                    # fix me later
                    image_id: int = 0

                    if image_id > 0:
                        if image_id not in keys:
                            bot.say("I don't have an image with id: {0}".format(image_id), channel_.get_channel_name())
                            return
                    else:
                        loop_count: int = 0
                        while True:
                            if len(keys) >= 1:
                                #num = random.randint(0, len(keys) - 1)
                                #image_id = keys[num]
                                image_id = random.choice(keys)
                                url = channel_.image_dictionary.get_url(image_id)
                                if not (('.mp4' in url) or ('.webm' in url)):
                                    channel_.gameplay.set_game_image(image_id)
                                    bot.say('{2} gimme some love [{0}]: {1}'.format(image_id, url, '[game,auto]'),
                                            channel_.get_channel_name())
                                    break
                                else:
                                    #bot.say('{2} skipping video [{0}]: {1}'.format(image_id, url, '[game,auto]'),
                                    #        channel_.get_channel_name())
                                    loop_count += 1
                                    if loop_count > 4:
                                        bot.say('{1} giving up after {0} tries'.format(loop_count, '[game,auto]'),
                                                channel_.get_channel_name())
                                        break
                            else:
                                bot.say('{0}: Please add images to {1}}'.format('[game,auto]',
                                                                                channel_.get_channel_name()),
                                        channel_.get_channel_name())
                                break
                return

            delay_remaining = self.delay - self.current_delay
            if delay_remaining > 0:
                if delay_remaining == self.delay:
                    time_remaining = formatting.color(formatting.bold('{0}'.format(delay_remaining)),
                                                      formatting.colors.BLUE)
                    bot.say("{2}: round {0} {1} seconds of love"
                            .format(self.current_round, time_remaining, '[game,auto]'),
                            channel_.get_channel_name())

                self.current_delay += 1
                if delay_remaining < 6:
                    time_remaining = formatting.color(formatting.bold('{0}'.format(delay_remaining)),
                                                      formatting.colors.RED)
                    bot.say("{2}: round {0} time remaining: {1}"
                            .format(self.current_round, time_remaining, '[game,auto]'),
                            channel_.get_channel_name())
                return

            rounds_remaining = self.rounds - self.current_round
            channel_.gameplay.next_image(channel_key_)
            scores = channel_.gameplay.get_scores()
            if (len(scores)):
                channel_.gameplay.show_channel_scores(bot, channel_key_, scores)

            self.current_image_id = 0
            self.current_pause = 0
            self.current_delay = 0

            if not rounds_remaining:
                self.autogame = False
                self.game_on = False
                bot.say('{0} {1}'.format('[game,auto]',
                                         formatting.color(formatting.italic(formatting.bold('Game Over')),
                                                          formatting.colors.BLUE)),
                        channel_.get_channel_name())
        return

    def start_game(self, auto_ = False):
        self.game_on = True
        self.autogame = auto_
        self.nick_loves: dict[str, dict[ int, int ]] = {}
        self.current_image_id: int = 0
        self.players.clear()
        return

    def stop_game(self, channel_key_: str):
        self.game_on = False
        if self.current_image_id:
            channel = channel_data[channel_key_]
            channel.image_dictionary.checkpoint()
            self.update_scores(channel_key_)
            self.current_image_id = 0
        return

    def next_image(self, channel_key_: str):
        if self.current_image_id:
            channel = channel_data[channel_key_]
            channel.image_dictionary.checkpoint()
            self.update_scores(channel_key_)
            self.current_image_id = 0
        return

    def set_game_image(self, image_id: int):
        self.current_image_id = image_id

    def filter_loves(self, loves: list[str]) -> list[str]:
        """ clean up the love here """
        filtered_loves: list[str] = []
        for love in loves:
            if len(love):
                stripped_love = love.lstrip().rstrip()
                if len(stripped_love):
                    filtered_loves.append(stripped_love)
        return filtered_loves

    def add_loves(self, channel_key_: str, nick_: str, loves_: list[str]):
        """

        :param nick:
        :param loves:
        :return:
        """
        if self.current_image_id:
            if nick_ not in self.players:
                self.players[nick_] = Scorecard()
            self.players[nick_].update_loves(self.current_image_id, loves_)
            channel: ChannelData = channel_data[channel_key_]
            image: Image = channel.image_dictionary[self.current_image_id]
            if image:
                for love in loves_:
                    cat_id = channel.category_dictionary.add_category(love.lower())
                    if not image.has_category(cat_id):
                        self.players[nick_].icrement_creates()
                    image.add_category(cat_id, 1)

                channel.image_dictionary[self.current_image_id] = image
        return

    def update_scores(self, channel_key_: str):
        for nick in self.players:
            score = self.players[nick].update_scores(channel_key_, self.current_image_id)
            # bot.say("{0} has {1} points".format(nick_, score))

    def get_scores(self)-> list[tuple[str,str]]:
        scores: list[tuple[str,str]] = []
        for nick in self.players:
            scores.append((nick, str(self.players[nick].score)))
        return scores

    def show_scores(self, bot: sopel.bot.SopelWrapper, scores: list[tuple[str,str]]):
        bot.say(formatting.bold(formatting.italic("Game Scorecard:")))
        for nick,score in scores:
            formatted_nick = formatting.color(formatting.bold(nick), formatting.colors.BLUE)
            formatted_score = formatting.color(formatting.bold(score), formatting.colors.RED)
            bot.say("{0} has {1} points".format(formatted_nick, formatted_score))

    def show_channel_scores(self, bot: sopel.bot.SopelWrapper, channel_key_: str, scores: list[tuple[str,str]]):
        channel: ChannelData = channel_data[channel_key_]
        bot.say(formatting.bold(formatting.italic("Game Scorecard:")), channel.get_channel_name())
        for nick,score in scores:
            formatted_nick = formatting.color(formatting.bold(nick), formatting.colors.BLUE)
            formatted_score = formatting.color(formatting.bold(score), formatting.colors.RED)
            bot.say("{0} has {1} points".format(formatted_nick, formatted_score), channel.get_channel_name())

    def reset_scores(self):
        self.players.clear()

def fetch_delay(value: str) -> int:
    """
    :param value: string to be converted to a delay value in seconds
    :return: if positive, the delay value, if neg, failed to parse
    Parse a delay vale
    """
    delay: int = -1
    try:
        if value.endswith('h'):
            multiplier = 60*60
            delay = int(value.split('h')[0]) * multiplier
        elif value.endswith('m'):
            multiplier = 60
            delay = int(value.split('m')[0]) * multiplier
        elif value.endswith('s'):
            delay = int(value.split('s')[0])
        else:
            delay = int(value)
    except ValueError:
        delay = -1
    return delay


class Announcement:
    """
    This class handles the annoucements for channels
    """
    def __init__(self, bot: sopel.irc.AbstractBot, channel_key: str, channel_name: str):
        """
        Initializse the class
        :param channel_key:
        """
        # channel announcement
        self.channel_key = channel_key
        self.channel_name = channel_name
        self.announce_on = False
        self.announce_delay = 15 * 60
        self.announce_counter = 0
        self.announce_message: str = \
            f'Welcome to {self.channel_name}! To obtain the rules, please type <b>!rules<b> in the channel. Thanks!'
        self.announce_dict: dist[str, str] = {'announce': self.announce_message,
                                              'delay': '900'}
        self.formatted_message: str = ''

        channel_announce_file = "{0}{1}".format(self.channel_key, "_announce.json")
        self.channel_announce_file: str = os.path.join(bot.config.core.homedir, channel_announce_file)
        if os.path.exists(self.channel_announce_file):
            with(io.open(self.channel_announce_file, 'r', encoding="utf-8")) as announce_file:
                self.announce_dict = json.load(announce_file)
        self.announce_message = self.announce_dict['announce']
        self.formatted_message = self.format_message(self.announce_message)
        self.announce_delay = int(self.announce_dict['delay'])
        self.announce_counter = 0

    def checkpoint(self):
        with(io.open(self.channel_announce_file,'w',encoding='utf-8')) as announce_file:
            json.dump(self.announce_dict, announce_file, ensure_ascii=False)

    def format_message(self, message:str) -> str:
        # some formatting primatives
        formats: dict[str, str] = {
            '<b>': bytes.fromhex('02').decode(encoding='utf-8', errors='ignore'),
            '<i>': bytes.fromhex('1D').decode(encoding='utf-8', errors='ignore'),
            '<u>': bytes.fromhex('1F').decode(encoding='utf-8', errors='ignore'),
            '{chan}' : self.channel_name
        }
        for key in list(formats.keys()):
            message = message.replace(key,formats[key])
        return message

    def set_annouce_message(self, announce_message):
        self.announce_dict['announce'] = announce_message
        self.announce_message = announce_message
        self.formatted_message = self.format_message(self.announce_message)
        self.checkpoint()

    def get_announce_enable(self) -> bool:
        return self.announce_on

    def set_announce_enabe(self, val: bool):
        self.announce_on = val

    def set_annouce_delay(self, delay: int):
        self.announce_delay = delay
        self.announce_dict['delay'] = delay
        self.checkpoint()

    def should_announce(self):
        self.announce_counter -= 1
        if self.announce_counter <= 0:
            self.announce_counter = self.announce_delay;
            return True
        else:
            return False;

    def make_announcement(self, bot: sopel.bot.SopelWrapper):
        bot.say(self.formatted_message, self.channel_name)


def DoAutoVoice(*args):
    key = args[0]
    nick = args[1]
    bot = args[2]

    if channel_data[key].autovoice.has_user(str(nick)):
        bot.write(['MODE', channel_data[key].get_channel_name(), "+v", nick])
        channel_data[key].autovoice.set_nick_time(nick, datetime.datetime.now())


def DoUnAutoVoice(*args):
    key = args[0]
    nick = args[1]
    bot = args[2]

    if channel_data[key].autovoice.has_user(nick):
        channel_data[key].autovoice.set_nick_time(nick, datetime.datetime.now())

class AutoVoice():
    """ maintains the list of autovoiced users
    """
    def __init__(self, autovoice_file_name: str, channel_name: str):
        super().__init__()
        self.channel_name = channel_name
        self.autovoice_file_name: str = autovoice_file_name
        self.autovoice_file_json: str = self.autovoice_file_name.replace('.csv','.json')
        self.users: dict[str, datetime.datetime] = {}
        self.userstore: dist[str,str] = {}
        self.mutex: threading.Lock = threading.Lock()

    def read_users(self):
        if os.path.exists(self.autovoice_file_json):
            with(io.open(self.autovoice_file_json, 'r', encoding="utf-8")) as chan_voice:
                self.userstore = json.load(chan_voice)

            for nick in self.userstore:
                self.users[nick] = datetime.datetime.fromisoformat(self.userstore[nick])

            self.purge_nicks(datetime.timedelta(days=30))

        elif os.path.exists(self.autovoice_file_name):
            cur_time : datetime.datetime  = datetime.datetime.now()
            with(io.open(self.autovoice_file_name, 'r', encoding="utf-8")) as chan_voice:
                for nick in chan_voice:
                    nick = nick.split('\n')[0]
                    if nick and (nick not in self.users.keys()):
                        self.users[nick] = cur_time
            self.write_users_nolock()

    def purge_nicks(self, delta: datetime.timedelta):
        now: datetime.datetime = datetime.datetime.now()
        purge: list[str] = []
        for nick in self.users.keys():
            nick_time: datetime.datetime = self.users[nick]
            if (now - nick_time) > delta:
                purge.append(nick)

        for nick in purge:
            del self.users[nick]
            del self.userstore[nick]

    def write_users_nolock(self):
        self.purge_nicks(datetime.timedelta(days=30))
        with(io.open(self.autovoice_file_json, 'w', encoding="utf-8")) as chan_voice:
            json.dump(self.userstore, chan_voice, indent='\t')

    def write_users(self):
        with self.mutex:
            self.write_users_nolock()

    def add_user(self, user_: str):
        with self.mutex:
            self.users[user_] = datetime.datetime.now()
            self.userstore[user_] = self.users[user_].isoformat()
            self.write_users_nolock()

    def set_nick_time(self, nick: str, new_time):
        with self.mutex:
            if nick in self.users.keys():
                self.users[nick] = new_time
                self.userstore[nick] = self.users[nick].isoformat()
                #self.write_users_nolock()

    def remove_user(self, user_: str):
        with self.mutex:
            if user_ in self.users.keys():
                del self.users[user_]
                del self.userstore[user_]
                self.write_users_nolock()

    def list_users(self) -> list[str]:
        users: list[str] = []
        with self.mutex:
            users = self.users.copy()
        users.sort()
        return users

    def has_user(self, user_: str) -> bool:
        hasUser: bool = False
        with self.mutex:
            hasUser =  user_ in self.users.keys()
        return hasUser

    def check_users(self, bot: sopel.bot.SopelWrapper):
        channel = bot.channels[self.channel_name]
        voice_nicks: list[str] = []
        if bot.has_channel_privilege(self.channel_name, plugin.OP):
            with self.mutex:
                for nick in channel.users:
                    if str(nick) in self.users.keys():
                        if not channel.has_privilege(nick, plugin.VOICE):
                            self.set_nick_time(str(nick), datetime.datetime.now())
                            voice_nicks.append(str(nick))
            for nick in voice_nicks:
                bot.write(['MODE', self.channel_name, "+v", nick])


class UrlChecker():
    """
    This data is used by the check_url_callback to cycle thru the channels and files

    current_channel_key is the key for the current channel we are checking the urls in
    current_image_list is a snapshot of the image id's in the current channel
    current_image_idx is the high water mark of the checking process

    the interval timer is 15 seconds so we will check 4 urls in a minute or 60 * 4 = 240 urls an hour
    """
    def __init__(self, channel_key_: str):
        self.busy: bool = False
        self.channel_key: str = channel_key_
        self.enabled: bool = False
        self.paused = False
        self.image_list: list[int] = []
        self.image_idx: int = 0
        self.last_image_idx: int = 0
        self.update_count: int = 0
        self.update_inc: int = 0

    def enable(self) -> bool:
        if self.enabled:
            LOGGER.info("url_checker already enabled for {0}".format(self.channel_key))
            return
        else:
            LOGGER.info("enable url_checker for {0}".format(self.channel_key))
            if self.last_image_idx == 0:
                self.image_list = list(channel_data[self.channel_key].image_dictionary)
                self.image_list.sort(reverse=True)
                self.update_inc = int((len(self.image_list)+3)/4)
                if self.update_inc < 1:
                    self.update_inc = 1
            self.image_idx = self.last_image_idx
            self.update_count = self.update_inc
            while self.image_idx > self.update_count:
                self.update_count += self.update_inc
            LOGGER.info("enable url_checker for {0}, total:{1} current:{2} update_inc:{3} update_count:{4}"
                        .format(self.channel_key,len(self.image_list), self.image_idx,
                                self.update_inc, self.update_count))
            self.enabled = True
        return self.enabled

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def is_paused(self) -> bool:
        return self.paused

    def disable(self) -> bool:
        self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled and not self.paused

    def checkImage(self, image: Image) -> bool:
        url: str = image.get_url()
        if self.checkUrl(url):
            # try to fix the shitty gyazo links
            if ('https://gyazo.com/' in url):
                url = url.replace('//gyazo', '//i.gyazo', 1) + '.xxx'
                extensions: list[tuple()] = [('.xxx', '.jpg'), ('.jpg', '.png'), ('.png', '.gif'), ('.gif', 'mp4')]
                for (a,b) in extensions:
                    url = url.replace(a,b,1)
                    if self.checkUrl(url):
                        # note the image_directory.checkpoint() function will update the images
                        image.set_url(url)
                        channel_data[self.channel_key].image_dictionary.set_image(image)
                        break;
            # not sure we get a 404 on bdsmlr links that move to ocdnXX.bdsmlr.com
            # so test if an ocdn version of the link exists
            elif ('.bdsmlr.com/' in url) and ('https://cdn' in url):
                url_chk: str = url.replace('//cdn', '//ocdn', 1)
                if self.checkUrl(url_chk):
                    # note the image_directory.checkpoint() function will update the images
                    image.set_url(url_chk)
                    channel_data[self.channel_key].image_dictionary.set_image(image)
                    LOGGER.info(f'replaced {url} with {url_chk}')
                    return True
            return True
        else:
            # this domain behaves oddly. returns 404 when vaild,
            # so punt and presume all are valid
            if '.icdn.ru' in url:
                return True
            # bdsmlr.com may change the content delivery node,
            # try a common fix
            elif ('.bdsmlr.com/' in url) or ('reblogme.com/' in url):
                return False
                #url = url.replace('//cdn', '//ocdn', 1)
                #if self.checkUrl(url):
                #    # note the image_directory.checkpoint() function will update the images
                #    image.set_url(url)
                #    channel_data[self.channel_key].image_dictionary.set_image(image)
                #    return True
                #else:
                #    return False
            else:
                return False

    def checkUrl(self, url: str) -> bool:
        """
        check url
        :param url: the url to check
        :type url: str
        :return: true if url is valid, false if not
        """
        # this domain behaves oddly. return 404 when valid, so punt and presume all are valid
        if '.icdn.ru' in url:
            return True
        # test here
        if 'bdsmlr.com/' in url:
            return False
        if 'reblogme.com/' in url:
            return False

        h = httplib2.Http('.cache', timeout=5)
        h.follow_redirects = True
        h.force_exception_to_status_code =True
        h.disable_ssl_certificate_validation = True
        (response_headers, content) = h.request(url,method="HEAD",body=None)
        status = response_headers.status
        resp_status = status;
        if  'status' in response_headers:
            resp_status: int = int(response_headers['status'])
        # special checks for imgur https://imgur.com or https://imgur.io/
        if (url.find('imgur.') > 0) and (status >= 200) and (status < 400):
            if 'content-type' in response_headers:
                content_type = response_headers['content-type']
                if content_type == 'text/html':
                    status = 404
            if 'content-location' in response_headers:
                content = response_headers['content-location']
                if content == 'https://i.imgur.com/removed.png':
                    status = 404
        return (status >= 200) and (status < 400)

    def process_callback(self, bot: sopel.bot.SopelWrapper):
        """
        This callback checks the URLS in the channel to make sure they are still valid, links that fail are
        put into a deleted_images.csv file.  This method is called 6 times per minute, so uppdates at 15 minute
        intervals would be 15 * 6 or 90 calls
        :param bot: this is the interface back to the bot, we will use it to send messages
        to the channels on the progress
        :return:
        """
        if self.busy:
            return

        self.busy = True
        channelData = channel_data[self.channel_key]
        if self.image_idx < len(self.image_list):
            image_id: int = self.image_list[self.image_idx]
            image: Image = channelData.image_dictionary.get_image(image_id)
            if image:
                LOGGER.info('channel {0}, Url check: image {1}: {2}'
                            .format(channelData.get_channel_name(), image_id, image.get_url()))
                if not self.checkImage(image):
                    LOGGER.info('channel {0}, Url check removing image {1}: {2}'
                                .format(channelData.get_channel_name(), image_id, image.get_url()))
                    # remove it
                    channelData.image_dictionary.delete_image(image_id)
            # move to next image
            self.image_idx += 1
            self.last_image_idx = self.image_idx
            if (self.image_idx > self.update_count):
                self.update_count += self.update_inc
                percent_complete: int = int((100 * self.image_idx)/len(self.image_list))
                bot.say('[url] url checker: {0}% complete'.format(percent_complete),
                        channelData.get_channel_name())
        else:
            bot.say('[url] url checker: 100% complete',channelData.get_channel_name())
            channelData.image_dictionary.renumber_images()
            bot.say('[url] url checker: Renumber complete', channelData.get_channel_name())
            self.image_list.clear()
            self.image_idx = 0
            self.last_image_idx = 0
            self.disable()
        self.busy = False

# additional features
# user profile (setup,view,update)
# birthday (bot sends a cake)
# drinks (drink add, drink serve <drink> <nick>
# food (food add, food serve <food> <nick>
# fact (fact add, fact (gets)
# topic (topic add, topic (gets)
# music (music add <link> <gendre>, music play <gendre>|<id>, music <list>
# quote (quote add author:quote, quote (gets random) quote author (gets quote from author)
# scene (scene add name:description, scene (gets random) scene name (gets named scene)

class Drinks:
    """ Drinks inplements a drink menu, you can add drinks, and server yourself (default) or
    serve a drink to someone in the channel
    """
    def __init__(self):
        pass

    def __init__(self, channel_name: str):
        """
        load the drinks file if it exists
        :param channel_name: name of channel
        """
        self.drink_menu : dict[str, str] = {}
        channel_drink_file = f"{channel_name}_drinks.json"
        self.channel_drink_file: str = os.path.join(bot.config.core.homedir, channel_drink_file)
        if os.path.exists(self.channel_drink_file):
            with(io.open(self.channel_drinks_file, 'r', encoding="utf-8")) as drinks_file:
                self.drink_menu = json.load(drinks_file)
        decode_drinks()
        self.dispatch_table = {
            '-menu': self.menu,
            '-m': self.menu,
            '-serve': self.serve,
            '-s': self.serve,
            '-add': self.add,
            '-a': self.add,
            '-instructions': self.descibe,
            '-i': self.descibe,
            '-delete': self.remove,
            '-d': self.remove,
        }

    def dispatch(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger):
        command: list[str] = trigger.split()
        command.pop(0)
        if len (command):
            request = command.pop(0)
            if request in self.dispatch_table:
                method = self.dispatch_table[request]
                method(bot, trigger, command)
            else:
                bot.say(f'Sorry {trigger.nick}, there is no drink command: {request}')
        else:
            bot.say(f'Sorry {trigger.nick}, you are missing the drink command')

    def menu(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def serve(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def add(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def describe(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def remove(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def checkpoint(self):
        """ save drinks to the drinks file
        """
        encode_drinks()
        with(io.open(self.channel_drink_file, 'w', encoding="utf-8")) as drinks_file:
            json.dump(self.drink_menu, drinks_file, indent='\t')

    def encode_drinks(self):
        """ encode the drinks data for json
        """
        for key in list(self.drink_menu):
            str = self.drink_menu[key].replace('"', '\"')
            self.drink_menu[key] = str

    def decode_drinks(self):
        """ decode the drink from from encoded form in json file
        """
        for key in list(self.drink_menu):
            str = self.drink_menu[key].replace('\"', '"')
            self.drink_menu[key] = str

    def add_drink(self,drink_name: str, drink_desc: str):
        self.drink_menu[drink_name] = drink_desc
        checkpoint()

    def get_drink(self, drink_name: str) -> str:
        if not drink_name:
            drink_name = random.choice(list(self.drink_menu))
        if drink_name in self.drink_menu:
            return self.drink_menu[drink_name];
        return None

    def del_drink(self, drink_name: str):
        if drink_name in self.drink_menu:
            del self.drink_menu[drink_name]
            checkpoint()

    def get_menu(self)-> list[str]:
        return list(self.drink_menu)

class Food:
    """ Drinks inplements a drink menu, you can add drinks, and server yourself (default) or
    serve a drink to someone in the channel
    """
    def __init__(self):
        pass

    def __init__(self, channel_name: str):
        """
        load the drinks file if it exists
        :param channel_name: name of channel
        """
        self.food_menu : dict[str, str] = {}
        channel_food_file = f"{channel_name}_food.json"
        self.channel_food_file: str = os.path.join(bot.config.core.homedir, channel_food_file)
        if os.path.exists(self.channel_food_file):
            with(io.open(self.channel_food_file, 'r', encoding="utf-8")) as drinks_file:
                self.drink_menu = json.load(drinks_file)
        self.decode_food()
        self.dispatch_table = {
            '-menu': self.menu,
            '-m': self.menu,
            '-serve' : self.serve,
            '-s' : self.serve,
            '-add' : self.add,
            '-a' : self.add,
            '-instructions' : self.descibe,
            '-i': self.descibe,
            '-delete' : self.remove,
            '-d' : self.remove,
        }

    def dispatch(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger):
        command: list[str] = trigger.split()
        command.pop(0)
        if len (command):
            request = command.pop(0)
            if request in self.dispatch_table:
                method = self.dispatch_table[request]
                method(bot, trigger, command)
            else:
                bot.say(f'Sorry {trigger.nick}, there is no food command: {request}')
        else:
            bot.say(f'Sorry {trigger.nick}, you are missing the food command')

    def menu(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def serve(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def add(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def describe(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def remove(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        pass

    def checkpoint(self):
        """ save food to the food file
        """
        self.encode_food()
        with(io.open(self.channel_food_file, 'w', encoding="utf-8")) as food_file:
            json.dump(self.food_menu, food_file, indent='\t')

    def encode_food(self):
        """ encode the food data for json
        """
        for key in list(self.food_menu):
            str = self.food_menu[key].replace('"', '\"')
            self.food_menu[key] = str

    def decode_food(self):
        """ decode the drink from from encoded form in json file
        """
        for key in list(self.food_menu):
            str = self.food_menu[key].replace('\"', '"')
            self.food_menu[key] = str

    def add_food(self, food_name: str, food_desc: str):
        self.food_menu[food_name] = food_desc
        self.checkpoint()

    def get_food(self, food_name: str) -> str:
        if not food_name:
            food_name = random.choice(list(self.food_mehu))
        if food_name in self.food_menu:
            return self.food_menu[food_name];
        return None

    def del_food(self, food_name: str):
        if food_name in self.food_menu:
            del self.food_menu[food_name]
            self.checkpoint()

    @property
    def get_menu(self) -> list[str]:
        return list(self.food_menu)

class Music:
    """ Music manages the music library per channel.
    User !music to return a random music url or
    !music <artist,genre,keyword> to play music whose description contains
    some of the text specified.
    !music -add <url> <genre,artist,song, etc> to add music to the library

    todo: this is a dict[int,dict] for json
    """
    def __init__(self):
        pass

    def __init__(self, channel_name: str):
        """
        load the music file if it exists
        :param channel_name: name of channel
        """
        self.musiclib : dict[ int, dict] = {}
        channel_music_file = f"{channel_name}_music.json"
        self.channel_music_file: str = os.path.join(bot.config.core.homedir, channel_music_file)
        if os.path.exists(self.channel_music_file):
            with(io.open(self.channel_music_file, 'r', encoding="utf-8")) as music_file:
                self.musiclib = json.load(music_file)
        decode_music()
        self.max_index = max(self.musiclib.keys()) + 1

    def checkpoint(self):
        """ save food to the food file
        """
        encode_music()
        with(io.open(self.channel_music_file, 'w', encoding="utf-8")) as music_file:
            json.dump(self.musiclib, music_file, indent='\t')

    def encode_music(self):
        """ encode the food data for json
        """
        for key in list(self.musiclib):
            str = self.musiclib[key]['description'].replace('"', '\"')
            self.musiclib[key]['description'] = str

    def decode_music(self):
        """ decode the drink from from encoded form in json file
        """
        for key in list(self.food_menu):
            str = self.musiclib[key]['description'].replace('\"', '"')
            self.musiclib[key]['description'] = str

    def add_music(self, ketwords: str, description: str):
        self.musiclib[food_name] = food_desc
        checkpoint()

    def get_food(self, food_name: str) -> str:
        if not food_name:
            food_name = random.choice(list(self.food_mehu))
        if food_name in self.food_menu:
            return self.food_menu[food_name];
        return None

    def del_food(self, food_name: str):
        if food_name in self.food_menu:
            del self.food_menu[food_name]
            checkpoint()

class Story:
    def __init__(self):
        pass

    def __init__(self, channel_name):
        self.mutex = threading.Lock()
        self.story: list[str] = []
        self.characters: dict[str, list[str]] = {}
        self.dispatch_table = {
            '-tail'             : self.tail,
            '-t'                : self.tail,
            '-print'            : self.print,
            '-p'                : self.print,
            '-add'              : self.add,
            '-a'                : self.add,
            '-insert'           : self.insert,
            '-i'                : self.insert,
            '-delete'           : self.delete,
            '-d'                : self.delete,
            '-rewind'           : self.rewind,
            '-r'                : self.rewind,
            '-add_character'    : self.add_character,
            '-ac'               : self.add_character,
            '-del_character'    : self.delete_character,
            '-dc'               : self.delete_character,
            '-list_characters'  : self.list_characters,
            '-lsc'              : self.list_characters,
            '-add_bio'          : self.add_bio,
            '-ab'               : self.add_bio,
            '-del_bio'          : self.delete_bio,
            '-db'               : self.delete_bio,
            '-insert_bio'       : self.insert_bio,
            '-ib'               : self.insert_bio,
            '-print_bio'        : self.print_bio,
            '-pb'               : self.print_bio,
            '-pc'               : self.print_bio }
        self.channel_name = channel_name
        self.story_filename = ''
        self.chars_filename = ''
        self.story: list[str] = []
        self.characters: dict[str, list[str]] = {}

    def load_story(self, story_filename, chars_filename):
        self.story_filename = story_filename
        self.chars_filename = chars_filename
        with(self.mutex):
            if os.path.exists(self.story_filename):
                with(io.open(self.story_filename, 'r', encoding='utf-8')) as story_file:
                    for line in story_file:
                        self.story.append(line)

            if os.path.exists(self.chars_filename):
                with (io.open(self.chars_filename, 'r', encoding='utf-8')) as chars_file:
                    self.characters = json.load(chars_file)

    def save_story(self):
        with(self.mutex):
            with(io.open(self.story_filename, 'w', encoding='utf-8')) as story_file:
                for line in self.story:
                    story_file.writelines(self.story)

            with (io.open(self.chars_filename, 'w', encoding='utf-8')) as chars_file:
                json.dump(self.characters, chars_file, indent='\t')

    def save_just_story(self):
        with(self.mutex):
            with(io.open(self.story_filename, 'w', encoding='utf-8')) as story_file:
                for line in self.story:
                    story_file.writelines(self.story)

    def save_just_characters(self):
        with(self.mutex):
            with (io.open(self.chars_filename, 'w', encoding='utf-8')) as chars_file:
                json.dump(self.characters, chars_file, indent='\t')


    def dispatch(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger):
        command: list[str] = trigger.split()
        command.pop(0)
        if len (command):
            request = command.pop(0)
            if request in self.dispatch_table:
                method = self.dispatch_table[request]
                method(bot, trigger, command)
            else:
                bot.say(f'Sorry {trigger.nick}, there is no story command: {request}')
        else:
            bot.say(f'Sorry {trigger.nick}, you are missing the story command')

    
    def tail(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ prints the last nn lines in the story
        """
        nlines: int = 10
        if len(command) > 0:
            if command[0].isdigit():
                n_lines = int(command[0])
                if n_lines > 20:
                    nlines = 20
                elif nlines < 1:
                    nlines = 1
            else:
                bot.say(f'{command[0]} is not an integer')
                return
        if len(self.story) == 0:
            bot.say('no story yet.')
            return
        if len(self.story) < nlines:
            nlines = len(self.story)
        start = len(self.story) - nlines;
        while start < len(self.story):
            text: str = self.story[start]
            text = text.rstrip('\n')
            bot.say(f'{start}: {text}')
            start += 1

    def print(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ prints  a snippet of the story starting at startline for count lines
        """
        nlines: int = 10
        start: int = 0
        end: int = 0
        if len(command) > 0:
            if command[0].isdigit():
                start = int(command[0])
                lines : int = len(self.story)
                if start > len(self.story):
                    bot.say(f'The story is only {lines} lines, try a start value < {len(self.story)}')
                    return
                command.pop(0)

            if (len(command) > 0) and command[0].isdigit():
                n_lines = int(command[0])
                if n_lines > 20:
                    nlines = 20
                elif nlines < 1:
                    nlines = 1

        if (len(self.story)-start) < nlines:
            nlines = len(self.story)-start

        end = start + nlines
        while start < end:
            text: str = self.story[start]
            text = text.rstrip('\n')
            bot.say(f'{start}: {text}')
            start += 1
    
    def add(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """adds <text> in a line to the story
        """
        text: str = ' '.join(command) + '\n'
        with(self.mutex):
            with(io.open(self.story_filename, 'a', encoding='utf8')) as story_file:
                self.story.append(text)
                story_file.write(text)
        text = text.rstrip('\n')
        bot.say(f'added "{text}" to story')

    def insert(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ inserts a line of text before line NN
        """
        if len(command) > 0:
            if command[0].isdigit():
                insert_before = int(command[0])
                command.pop(0)
                if insert_before < 0:
                    insert_before = 0
                elif insert_before >= len(self.story):
                    self.story.add(bot, trigger, command)
                else:
                    text: str = ' '.join(command) + '\n'
                    self.story.insert(insert_before, text)
                    self.save_just_story()
                    text = text.rstrip('\n')
                    bot.say(f'inserted "{text}" at line {insert_before} ')

    def delete(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ deletes line NN from the story
        """
        if len(command) > 0:
            if command[0].isdigit():
                delete_line = int(command[0])
                command.pop(0)
                if (delete_line >= 0) and (delete_line < len(self.story)):
                    self.story.pop(delete_line)
                    self.save_just_story()
                    bot.say(f'deleted line {delete_line}')
                else:
                    bot.say(f'{delete_line} out of range.')
            else:
                bot.say(f'{command[0]} is not an integer')
        else:
            bot.say('missing line number')

    
    def rewind(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ deletes the story after line NN
        """
        if len(command) > 0:
            if command[0].isdigit():
                delete_line = int(command[0])
                command.pop(0)
                if (delete_line >= 0) and (delete_line < len(self.story)):
                    del self.story[delete_line+1 : len(self.story)]
                    self.save_just_story()
                    bot.say(f'story rewound to line {delete_line}')
            else:
                bot.say(f'{command[0]} is not an integer')
        else:
            bot.say('missing line number')



    def add_character(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ adds a character to the story
        """
        if len(command) > 0:
            person = command.pop(0)
            if person in self.characters:
                bot.say(f'{person} is already in the list of characters.')
            else:
                empty_list: list[str] = []
                self.characters[person] = empty_list
                self.save_just_characters()
                bot.say(f'added {person} to the list of characters')

    def delete_character(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ deletes character <name> and the bio
        """
        if len(command) > 0:
            person = command.pop(0)
            if person in self.characters:
                del self.characters[person]
                self.save_just_characters()
                bot.say(f'deleted character: {person}')
            else:
                bot.say(f'{person} is not in the list of characters.')

    def list_characters(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        characters = ', '.join(self.characters.keys())
        bot.say(f'Current list of characters: {characters}')


    def add_bio(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        """ adds information on the character <name>
        """
        if len(command) > 0:
            person = command.pop(0)
            text = ' '.join(command)
            if person in self.characters:
                self.characters[person].append(text)
                bot.say(f'added "{text}" for {person}')

            else:
                text_list : list[str] = []
                text_list.append(text)
                self.characters[person] = text_list
                bot.say(f'added {person} with bio "{text}"')
            self.save_just_characters()
        else:
            bot.say('missing character name')

    def delete_bio(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command: list[str]):
        """ deletes line NN from charater bio
        """
        if len(command) > 0:
            person = command.pop(0)
            if person in self.characters:
                if len(command) > 0:
                    if command[0].isdigit():
                        delete_line = int(command[0])
                        command.pop(0)
                        if (delete_line >= 0) and (delete_line < len(self.characters[person])):
                            self.characters[person].pop(delete_line)
                            self.save_just_characters()
                        else:
                            bot.say(f'line {delete_line} out of range')
                    else:
                        bot.say('can not parse the line number.')
                else:
                    bot.say('missing line number')
            else:
                bot.say(f'{person} is not a character.')
        else:
            bot.say('missing arguments')


    def insert_bio(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """ insert a line in the bio of character <name> before NN
        """
        if len(command) > 0:
            person = command.pop(0)
            if person in self.characters:
                if len(command) > 0:
                    if command[0].isdigit():
                        insert_line = int(command[0])
                        command.pop(0)
                        text: str = ' '.join(command)
                        if (insert_line >= 0) and (insert_line < len(self.characters[person])):
                            self.characters[person].insert(text)
                            self.save_just_characters()
                            bot.say(f'inserted "{text}" at line {inserted_line} for {person}')
                        else:
                            bot.say(f'sorry, {insert_line} is out of range')
                    else:
                        bot.say('missing or malformed insert location')
                else:
                    bot.say('missing insert location')
            else:
                bot.say(f'{person} is not a known character' )
        else:
            bot.say('missing character.')

    def print_bio(self, bot: sopel.irc.AbstractBot, trigger: sopel.trigger, command : list[str]):
        """prints the character <name> bio
        """
        if len(command) > 0:
            person = command.pop(0)
            if person in self.characters:
                bot.say(f'bio for {person}')
                line_count = 0;
                for line in self.characters[person]:
                    bot.say(f'{line_count}: {line}')
                    line_count += 1
            else:
                bot.say(f'{person} is not a character.')



class ChannelData:
    """ ChannelData contains the id, url and category information for each channel
    The bot will keep the channels unique, the data is keyed to the channel name
    """
    def __init__(self):
        pass

    def __init__(self, bot: sopel.irc.AbstractBot, channel_: str, channel_name_: str):
        """
        initialize this channel data
        :param bot:
        :param channel_:
        :param channel_name_:
        """
        self.mutex: threading.Lock = threading.Lock()
        self.idleMutex : treading.Lock = threading.Lock()

        self.channel_name = channel_name_
        # get just the channel name
        self.base_channel_name = channel_

        # note: we can read the catagories configuration frm teh default.cfg file
        # like this
        self.max_categories = bot.config.categories.max_categories
        self.default_rounds = bot.config.categories.default_rounds
        self.default_delay = bot.config.categories.default_delay
        self.default_pause = bot.config.categories.default_pause
        self.enabled_commands = bot.config.categories.enabled_commands

        # some channel owners don't want all features, read the channel features file if it exists
        # if the features file doesn't exist all features are enabled, features can be limited to
        # operators, voiced users, all users, or disabled. each command can be eitehr
        # 'enabled', 'operator', 'voice', or 'disabled'
        # { "add" : "voice" }
        channel_features_file = "{0}{1}".format(self.base_channel_name, "_features.json")
        self.features : dict[str, str] = {}
        self.channel_features_file: str = os.path.join(bot.config.core.homedir, channel_features_file)
        if os.path.exists(self.channel_features_file):
            with(io.open(self.channel_features_file, 'r', encoding="utf-8")) as features_file:
                self.features = json.load(features_file)


        # the category file
        base_cats_file = "{0}{1}".format(self.base_channel_name, "_categories.csv")
        self.cat_file_name = os.path.join(bot.config.core.homedir, base_cats_file)
        self.category_dictionary: CategoryDictionary = CategoryDictionary(self.cat_file_name)
        if os.path.exists(self.cat_file_name):
            self.category_dictionary.read_categories()

        # the urls file
        base_urls_file = "{0}{1}".format(self.base_channel_name, "_images.csv")
        self.url_file_name = os.path.join(bot.config.core.homedir, base_urls_file)
        base_deleted_urls_file = "{0}{1}".format(self.base_channel_name, "_deleted_images.csv")
        self.deleted_url_file_name = os.path.join(bot.config.core.homedir, base_deleted_urls_file)
        self.image_dictionary: ImageDictionary = ImageDictionary(self.url_file_name, self.deleted_url_file_name)
        if os.path.exists(self.url_file_name):
            self.image_dictionary.read_images()

        # the autovoice
        base_autovoice_file = "{0}{1}".format(self.base_channel_name, "_autovoice.csv")
        self.autovoice_file_name = os.path.join(bot.config.core.homedir, base_autovoice_file)
        self.autovoice: AutoVoice = AutoVoice(self.autovoice_file_name, self.channel_name)
        self.autovoice.read_users()

        #kiss and spank
        channel_kiss_spank_file = "{0}{1}".format(self.base_channel_name, "_kiss_spank.json")
        self.channel_kiss_spank_file = os.path.join(bot.config.core.homedir, channel_kiss_spank_file)

        self.kiss_spank_dict = {}
        if not os.path.exists(self.channel_kiss_spank_file):
            channel_kiss_spank_file = "{0}{1}".format("default", "_kiss_spank.json")
            self.channel_kiss_spank_file = os.path.join(bot.config.core.homedir, channel_kiss_spank_file)

        if os.path.exists(self.channel_kiss_spank_file):
            with(io.open(self.channel_kiss_spank_file, 'r', encoding="utf-8")) as ks_file:
                self.kiss_spank_dict = json.load(ks_file)

        # channel rules
        self.rules_dict: dist[str,str] = {}
        channel_rules_file = "{0}{1}".format(self.base_channel_name, "_rules.json")
        self.channel_rules_file = os.path.join(bot.config.core.homedir, channel_rules_file)
        if os.path.exists(self.channel_rules_file):
            with(io.open(self.channel_rules_file, 'r', encoding="utf-8")) as rules_file:
                self.rules_dict = json.load(rules_file)

        #channel ops
        self.ops_dict: dict[str, str] = {}
        channel_ops_file = "{0}{1}".format(self.base_channel_name, "_ops.json")
        self.channel_ops_file = os.path.join(bot.config.core.homedir, channel_ops_file)
        if os.path.exists(self.channel_ops_file):
            with(io.open(self.channel_ops_file, 'r', encoding="utf-8")) as ops_file:
                self.ops_dict = json.load(ops_file)

        #channel announcement
        self.announcement: Announcement = Announcement(bot, self.base_channel_name, self.channel_name)

        # autoplay
        self.autoplay: Autoplay = Autoplay()

        # gameplay
        self.gameplay: GamePlay = GamePlay(self.default_rounds, self.default_delay, self.default_pause)

        # verbosity level
        self.verbosity = 3

        # url checker instance
        self.url_checker = UrlChecker(self.base_channel_name)

        # channel max nick idle time
        self.idle_max = datetime.timedelta.max
        self.idle_dict: dict[str,int] = {}
        self.idle_dict['idle_time'] = 0

        channel_idle_file = "{0}{1}".format(self.base_channel_name, "_idle.json")
        self.channel_idle_file = os.path.join(bot.config.core.homedir, channel_idle_file)
        if os.path.exists(self.channel_idle_file):
            with(io.open(self.channel_idle_file, 'r', encoding="utf-8")) as idle_file:
                self.idle_dict = json.load(idle_file)
                timeout = self.idle_dict['idle_time']
                if timeout > 0:
                    self.idle_max = datetime.timedelta(seconds=timeout)
                else:
                    self.idle_max = datetime.timedelta.max

        self.idle_users: dict[str, datetime.datetime] = {}

        self.story = Story(self.channel_name)
        channel_story_file = "{0}{1}".format(self.base_channel_name, "_story.txt")
        channel_characters_file = "{0}{1}".format(self.base_channel_name, "_characters.json")
        self.channel_story_file = os.path.join(bot.config.core.homedir, channel_story_file)
        self.channel_characters_file = os.path.join(bot.config.core.homedir, channel_characters_file)
        self.story.load_story(self.channel_story_file, self.channel_characters_file)

        # temporary channel bans
        self.ban_lock: threading.Lock = threading.Lock()
        self.temporary_bans: dict[str, datetime.datetime] = {}

        # do housekeepking chores
        self.run_housekeeping()
        return

    def on_idle_callback(self, bot: sopel.bot.SopelWrapper):
        """ this is called every minute, if there is a idle timeout set for the channel,
        then users that exceed the idle time will be kicked
        """
        current_time: datetime.datetime = datetime.datetime.now()
        this_channel = bot.channels[self.channel_name]
        with self.idleMutex:
            users = this_channel.users.keys()
            kickUsers: list[str] = []
            for nick in users:
                if not this_channel.has_privilege(nick, plugin.OP):
                    if nick in self.idle_users.keys():
                        nick_idle = self.idle_users[nick]
                        if (current_time - nick_idle) > self.idle_max:
                            kickUsers.append(nick)
                    else:
                        self.idle_users[nick] = current_time
            for nick in kickUsers:
                del self.idle_users[nick]

        for nick in kickUsers:
            bot.kick(nick, self.channel_name,
                     f'Sorry {nick}, you are idle too long, come back to {self.channel_name} when awake')

    def update_nick_idle(self, bot: sopel.bot.SopelWrapper, nick: str):
            if not bot.nick in nick:
                this_channel = bot.channels[self.channel_name]
                if bot.has_channel_privilege(self.channel_name, plugin.OP):
                    if not this_channel.has_privilege(nick, plugin.OP):
                        with self.idleMutex:
                            self.idle_users[nick] = datetime.datetime.now()

    def update_idle_nicks(self, bot: sopel.bot.SopelWrapper, old, new ):
        with self.idleMutex:
            if old in self.idle_users.keys():
                time = self.idle_users[old]
                self.idle_users[new] = time
                del self.idle_users[old]

    def remove_idle_user(self, bot: sopel.bot.SopelWrapper, nick: str):
        with self.idleMutex:
            if nick in self.idle_users.keys():
                del self.idle_users[nick]

    def set_idle_time(self, bot: sopel.bot.SopelWrapper, timeout: int) -> bool:
        if timeout <= 0:
            self.idle_max = datetime.timedelta.max
            self.idle_dict['idle_time'] = 0
        else:
            self.idle_max = datetime.timedelta(seconds=timeout)
            self.idle_dict['idle_time'] = timeout

        with self.idleMutex:
            with(io.open(self.channel_idle_file, 'w', encoding="utf-8")) as idle_file:
                json.dump(self.idle_dict, idle_file, indent='\t')

            if self.idle_max < datetime.timedelta.max:
                for nick in bot.channels[self.channel_name].users.keys():
                    if not bot.nick in nick:
                        this_channel = bot.channels[self.channel_name]
                        if not this_channel.has_privilege(nick, plugin.OP):
                            self.idle_users[str(nick)] = datetime.datetime.now()
            else:
                self.idle_users.clear()
        return True

    def expire_temporary_bans(self, bot: sopel.bot.SopelWrapper):
        now = datetime.datetime.now()
        with self.ban_lock:
            targets: list[str] = self.temporary_bans.keys()
            for target in targets:
                if target in self.temporary_bans:
                    if now > self.temporary_bans[target]:
                        bot.write(['MODE', self.channel_name, "-b", target])
                        del self.temporary_bans[target]

    def kickban(self, bot: sopel.bot.SopelWrapper, user: sopel.tools.target.User, delay: int):
        expire_time: datetime.datetime = datetime.datetime.now() + datetime.timedelta(seconds=delay)
        target = f'*!{user.user}@{user.host}'
        with self.ban_lock:
            self.temporary_bans[target] = expire_time
        bot.write(['MODE', self.channel_name, "+b", target])
        bot.write(['KICK', self.channel_name, user.nick, f':take a break from {self.channel_name}'])

    def clear_all_temporary_bans(self):
        targets: list[str] = {}
        with self.ban_lock:
            targets = self.temporary_bans.keys()
            self.temporary_bans.clear()
        for target in targets:
            bot.write(['MODE', self.channel_name, "-b", target])

    def get_announcement(self) -> Announcement:
        return self.announcement

    def run_housekeeping(self):
        """
        This is the housekeeping chore, it now checks for duplicate keywords,
        removes them and updates the channel image directory
        :return:
        """
        did_replace: bool = False;
        did_deleted_replace: bool = False;
        replacement_keys : dict[int, int] = self.category_dictionary.find_duplicates()
        LOGGER.info("{0}: housekeeping found {1} duplicate keywords".format(self.get_channel_name(), len(replacement_keys)))
        if len(replacement_keys):
            LOGGER.info("{0} Checking Image dictionary, for duplicate keys".format(self.get_channel_name()))
            did_replace = self.image_dictionary.remove_duplicate_categories(replacement_keys)
            if did_replace:
                LOGGER.info("{0} Fixed Image dictionary, replaced duplicate keys".format(self.get_channel_name()))
            did_deleted_replace =self.image_dictionary.remove_duplicate_deleted_image_categories(replacement_keys)
            if did_deleted_replace:
                LOGGER.info("{0} Fixed deleted Image dictionary, replaced duplicate keys".format(self.get_channel_name()))

    def get_channel_name(self) -> str:
        return self.channel_name

    def is_command_enabled(self, bot: sopel.bot.SopelWrapper, trigger: sopel.trigger, cmd: str ) -> bool:
        if cmd not in self.features:
            return True
        else:
            option: str = self.features[cmd]
            channel = bot.channels[trigger.sender]
            if option == 'enabled':
                return True
            elif option == 'operator':
                if trigger.sender in bot.channels:
                    channel = bot.channels[trigger.sender]
                    return channel.has_privilege(trigger.nick, plugin.OP)
            elif option == 'voice':
                if trigger.sender in bot.channels:
                    channel = bot.channels[trigger.sender]
                    return channel.has_privilege(trigger.nick, plugin.VOICE)
            elif option == 'disabled':
                return False
            else:
                return False

    def get_image(self, id):
        if id in self.images:
            return self.images[id].url

    def get_kisses(self) -> list[str]:
        if 'kiss' in self.kiss_spank_dict:
            return self.kiss_spank_dict['kiss']
        else:
            return ['kisses {0}', 'loves {0}']

    def get_spanks(self) -> list[str]:
        if 'spank' in self.kiss_spank_dict:
            return self.kiss_spank_dict['spank']
        else:
            return ['spanks {0}', 'swats {0}']

    def get_rules(self):
        if 'rules' in self.rules_dict:
            return self.rules_dict['rules']
        else:
            return []

    def set_verbosity(self, vlevel: int) -> None:
        self.verbosity = vlevel

    def get_verbosity(self) -> int:
        return self.verbosity

    def is_allowed_ops(self, network: str, nick: str, user: str) -> bool:
        if network.find('undernet.org') >= 0:
            with self.mutex:
                if nick in self.ops_dict.keys():
                    return user == self.ops_dict[nick]
                else:
                    return False
        else:
            with self.mutex:
                if nick in self.ops_dict.keys():
                    return user == self.ops_dict[nick]
                else:
                    return False

    def get_allowed_ops_user(self, network: str, nick: str) -> str:
        if network.find('undernet.org') >= 0:
            with self.mutex:
                if nick in self.ops_dict.keys():
                    return self.ops_dict[nick]
                else:
                    return ''
        else:
            with self.mutex:
                if nick in self.ops_dict.keys():
                    return self.ops_dict[nick]
                else:
                    return ''

    def get_allowed_ops(self, network: str) -> list[ str ]:
        with self.mutex:
            return list(self.ops_dict)

    def add_allowed_op(self, network: str, nick: str, user: str) -> bool:
        with self.mutex:
            self.ops_dict[nick] = user
            with(io.open(self.channel_ops_file, 'w', encoding="utf-8")) as ops_file:
                json.dump(self.ops_dict, ops_file, indent='\t')
        return True

    def del_allowed_op(self, network: str, nick: str) -> bool:
        with self.mutex:
            if nick in self.ops_dict:
                del self.ops_dict[nick]
                with(io.open(self.channel_ops_file, 'w', encoding="utf-8")) as ops_file:
                    json.dump(self.ops_dict, ops_file, indent='\t')
                return True
        return False

    def checkpoint(self):
        self.close()

    def close(self):
        self.category_dictionary.checkpoint()
        self.image_dictionary.checkpoint()
        self.autovoice.write_users_nolock()
        self.clear_all_temporary_bans()
        return

@plugin.interval(60)
@plugin.output_prefix('[idle] ')
def idle_callback(bot: sopel.bot.SopelWrapper):
    """ idle timer, kick idle user """
    for channel_key in list(channel_data.keys()):
        channel = channel_data[channel_key]
        channel.on_idle_callback(bot)

class PendingOps:
    """
    This class handles the notification from X to me
    """
    def __init__(self):
        # these two lists are managed between the operator command and the
        # on_notice callback
        self.op_mutex : threading.Lock = threading.Lock()
        self.pending_allow_ops: dict[str, str] = {}
        self.pending_give_ops: dict[str, str] = {}

    def add_pending_allow_op(self, network: str, nick: str, cname: str) -> bool:
        pending: dict[str, str] = {}
        pending['network'] = network
        pending['channel'] = cname
        with self.op_mutex:
            if nick.casefold() not in self.pending_allow_ops:
                self.pending_allow_ops[nick.casefold()] = json.dumps(pending,indent='\t')
                return True
        return False

    def add_pending_give_op(self, network: str, nick: str, user: str, cname: str) -> bool:
        pending: dict[str, str] = {}
        pending['network'] = network
        pending['user'] = user
        pending['channel'] = cname
        with self.op_mutex:
            if nick.casefold() not in self.pending_give_ops:
                self.pending_give_ops[nick.casefold()] = json.dumps(pending, indent='\t')
                return True
        return False

    def fetch_pending_allow_ops(self, network: str, nick: str) -> str:
        json_str: str = ''
        with self.op_mutex:
            if nick.casefold() in self.pending_allow_ops:
                json_str = self.pending_allow_ops[nick.casefold()]
                del self.pending_allow_ops[nick.casefold()]
        return json_str

    def fetch_pending_give_ops(self, network: str, nick: str) -> str:
        json_str: str = ''
        with self.op_mutex:
            if nick.casefold() in self.pending_give_ops:
                json_str = self.pending_give_ops[nick.casefold()]
                del self.pending_give_ops[nick.casefold()]
        return json_str


""" this is the channel data for all the channels that the bot is in
"""
channel_data: dict[ str, ChannelData ] = {}
help_dict: dict[ str, dict[str, any]] = {}
game_dict: dict[ str, dict[str, any]] = {}
pending_ops: PendingOps = PendingOps()

def configure(settings):
    """ Configuration parameters for this plugin
    :param settings: the settings object
    :type sopel.config.Config
    """
    config.define_section('categories', CategoriesSection)
    config.categories.configure_setting('max_categories, "maximum number of catatories [10]?')


def setup(bot: sopel.bot.SopelWrapper):
    global help_dict
    global game_dict
    """ setup is called when the plugin is loaded
    :param bot: instance of the bot
    :type bot: sopel.bot.SopelWrapper
    """
    bot.config.define_section('categories', CategoriesSection)

    # load the help context
    help_file_name = os.path.join(bot.config.core.homedir, 'help.json')
    if os.path.exists(help_file_name):
        with(io.open(help_file_name, 'r', encoding="utf-8")) as help_file:
            help_dict = json.load(help_file)
        # 'command' is just for documentation purposes in help_dict, remove it.
        if 'command' in help_dict:
            del help_dict['command']

    game_file_name = os.path.join(bot.config.core.homedir, 'gameplay.json')
    if os.path.exists(game_file_name):
        with(io.open(game_file_name, 'r', encoding="utf-8")) as game_file:
            game_dict = json.load(game_file)

    for channel_ in bot.config.core.channels:
        channel_name: str = channel_.split()
        channel_key = channel_name[0].strip('#&').casefold()
        if channel_key not in channel_data.keys():
            channel_data[channel_key] = ChannelData(bot, channel_key, channel_name[0])

    plugins = sopel.plugins.find_sopel_modules_plugins()
    for key in plugins:
        pass
    sections = bot.config.get_defined_sections()
    bot.config.categories.enabled_commands
    pass

#
# shutdown
#
def shutdown(bot):
    """ shudown is called when the bot closes, we make updates to out persistant storage
    :param bot:
    :type sopel.config.Config
    """
    for channel_key in channel_data.keys():
        channel_data[channel_key].close()

def show_results(bot: sopel.bot.SopelWrapper, message: str, slice_size: int, data: list[any], dest:str):
    """
    show_results will output data as a series of bot.say() so we don't truncate the output and don't
    flood the server/client/channel
    :param bot:
    :param message: str with a single substitution parameter
    :param slice_size: maximum number of entries
    :param data: list of data items (to be converted to str)
    :param dest: channel or nick to send the message to

    :return:
    """
    slice_start: int = 0
    slice_end: int = slice_size
    while slice_start < len(data):
        if slice_end > len(data):
            slice_end = len(data)
        if dest:
            bot.say(message.format(', '.join(str(d) for d in data[slice_start: slice_end])), dest)
            #bot.notice(message.format(', '.join(str(d) for d in data[slice_start: slice_end])), dest)
        else:
            bot.say(message.format(', '.join(str(d) for d in data[slice_start: slice_end])))
        slice_start = slice_end
        slice_end = slice_start + slice_size;

#
# category matching
#
def match_categories(channel_: ChannelData, command: list[str], exact_match: bool = False) -> list[int]:
    """
    This method provides the matching logic for show and get key ...
    :param bot:
    :param channel_key:
    :param command category strings
    :return: lits of image id's that match the filter string
    """
    #channel_: ChannelData = channel_data[channel_key]
    keyword: str = ''
    keywords: list[str] = []
    keys: list[int] = []
    first_pass: bool = True
    while len(command):
        categories: list[int] = []
        keywords = command[0].split(',')
        for keyword in keywords:
            cats: list[int] = []
            if exact_match:
                cats = channel_.category_dictionary.find_matches_exact(parse.unquote_plus(keyword.lower()))
            else:
                cats = channel_.category_dictionary.find_matches(parse.unquote_plus(keyword.lower()))
            for cat in cats:
                categories.append(cat)
        if first_pass:
            keys: list[int] = channel_.image_dictionary.find_matches(categories)
            first_pass = False
        else:
            filter_keys: list[int] = channel_.image_dictionary.find_matches(categories)
            remove_keys: list[int] = []
            for key in keys:
                if key not in filter_keys:
                    remove_keys.append(key)
            for key in remove_keys:
                keys.remove(key)
        command.pop(0)
        if len(keys) == 0:
            break
    return keys

@plugin.command('test')
def on_test(bot: sopel.bot.SopelWrapper, trigger : sopel.trigger):
    """
    Test funtion
    :param bot: 
    :param trigger: 
    :return: 
    """
    if trigger.sender in bot.channels:
        channel = bot.channels[trigger.sender]
        channel_key: str = trigger.sender.strip('#&').casefold()
        channel_ = channel_data[channel_key]
        vlevel: int = channel_.get_verbosity()
        commands: list[str] = trigger.split()
        network = bot.config.core.host
        on_undernet: bool = 'undernet.org' in network
        nick: str = trigger.nick
        user = channel.users[nick].user
        hostmask: str = channel.users[nick].hostmask.casefold()
        valid_nick: bool = False
        commands.pop(0)
        if len(commands) == 0:
            # op the caller
            caller_host = channel.users[trigger.nick].hostmask.casefold()
            if on_undernet:
                regex = re.compile("(.+)!(.+)@(.+)\.(.+\..+\..+)")
                regex_match = regex.match(hostmask)
                if regex_match:
                    if regex_match.lastindex >= 4:
                        nick = regex_match.group(1)
                        user = regex_match.group(3)
                        valid_nick = regex_match.group(4).find('users.undernet.org') >= 0
                        valid_nick = False

                if valid_nick:
                    if not channel.has_privilege(nick, plugin.OP):
                        bot.write(['MODE', trigger.sender, "+o", nick])
                else:
                    channel_.add_pending_give_ops(nick)
                    bot.write(['PRIVMSG', 'X', ':VERIFY ', nick])
            else:
                bot.say("{0} isn't in the {1} allowed ops list".format(nick, channel_.get_channel_name()), trigger.nick)

@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('story', 'st')
@plugin.output_prefix('[story] ')
def on_story(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]
    channel_.story.dispatch(bot, trigger)


@plugin.require_bot_privilege(plugin.OP, 'Must be a channel operator')
@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('idle', 'set_idle')
@plugin.example('!idle 120m', 'set user idle to 120 minutes')
@plugin.example('!idle 3h', 'set user idle to 3 hours')
@plugin.output_prefix('[idle] ')
def on_set_idle(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    command: list[str] = trigger.split()
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]
    delay = 0
    command.pop(0)
    # check for specified delay 10, 10s, 10m
    if len(command):
        value: str = command.pop(0).lower()
        delay = fetch_delay(value)
        if delay < 0:
            bot.say(f"I don't understand a delay of {value}, ignoring idle timeout request")
            return
    if delay > 0:
        bot.say(f'User idle time set to {delay} seconds')
        channel_.set_idle_time(bot, delay)
    else:
        bot.say('User idle time disabled')
        channel_.set_idle_time(bot, 0)


@plugin.interval(10)
@plugin.output_prefix('[kickban] ')
def check_tempban_callback(bot: sopel.bot.SopelWrapper):
    """ Interval callback, set at one second
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    """
    for channel_ in channel_data:
        channel_data[channel_].expire_temporary_bans(bot)

@plugin.require_bot_privilege(plugin.OP, 'Please op me')
@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('kickban', 'kban', 'kb')
@plugin.example('!kickban nick <delay>', 'kicks and bans a user for delay time, default 60 seconds')
@plugin.example('!kb nick', 'kicks and bans user for 60 seconds')
@plugin.example('!kb nick 5m', 'kicks and bans user for 5 minutes')
@plugin.example('kickban -clear', 'clears all temporary bans')
@plugin.output_prefix('[kickban] ')
def on_kickban(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    command: list[str] = trigger.split()
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]
    delay = 0
    command.pop(0)
    if len(command):
        if '-clear' in command[0]:
            channel_.clear_all_temporary_bans(bot)
        else:
            nick = command.pop(0)
            if nick in channel.users:
                user = channel.users[nick]
                if len(command):
                    value = command.pop(0)
                    delay: int = fetch_delay(value)
                    if delay < 0:
                        delay = 60
                        bot.say(f'I don\'t understand a delay of {value}, using 60 seconds.')
                else:
                    delay = 60
                channel_.kickban(bot, user, delay)
            else:
                bot.say(f'{nick} isn\'t in the channel.')


@plugin.require_bot_privilege(plugin.OP, 'Please op me')
@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('operator', 'oper', 'op')
@plugin.example('!op nick', 'gives caller op privleges')
@plugin.example('!op add nick', 'adds nick to op list')
@plugin.example('!op del nick', 'removes nick from op list')
@plugin.example('!op list', "shows all auto-op people")
@plugin.output_prefix('[op] ')
def on_op(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """  handle the op, like aoutvoice nick
    :param bot:  instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    global pending_ops

    if trigger.sender in bot.channels:
        channel = bot.channels[trigger.sender]
        channel_key: str = trigger.sender.strip('#&').casefold()
        channel_ = channel_data[channel_key]

        # test for feature enable
        if not channel_.is_command_enabled(bot, trigger, "operator"):
            bot.say('{0} is not permitted in {1}'.format('operator', channel_.get_channel_name()))
            return

        vlevel: int = channel_.get_verbosity()
        commands: list[str] = trigger.split()
        network = bot.config.core.host
        on_undernet: bool = 'undernet.org' in network

        #micasa has an !op fantasy command in ChanServ, so don't attempt any op here
        if not on_undernet:
            return

        nick: str = trigger.nick
        user = channel.users[nick].user
        hostmask: str = channel.users[nick].hostmask.casefold()
        valid_nick: bool = False
        commands.pop(0)
        if len(commands) == 0:
            # op the caller
            caller_host = channel.users[trigger.nick].hostmask.casefold()
            if on_undernet:
                regex = re.compile("(.+)!(.+)@(.+)\.(.+\..+\..+)")
                regex_match = regex.match(hostmask)
                if regex_match:
                    if regex_match.lastindex >= 4:
                        nick = regex_match.group(1)
                        user = regex_match.group(3)
                        valid_nick = regex_match.group(4).find('users.undernet.org') >= 0

                if valid_nick:
                    if not channel.has_privilege(nick, plugin.OP):
                        if channel_.is_allowed_ops(network, nick.casefold(), user):
                            bot.write(['MODE', trigger.sender, "+ov", nick])
                    else:
                        if channel_.is_allowed_ops(network, nick.casefold(), user):
                            bot.write(['MODE', trigger.sender, "-o", nick])

                else:
                    # we don't vhost for the user
                    pending_ops.add_pending_give_op(network, nick.casefold(), 'Unknown', channel_.get_channel_name())
                    bot.write(['PRIVMSG', 'X', ':VERIFY ', nick])
            else:
                if not channel.has_privilege(nick, plugin.OP):
                    if channel_.is_allowed_ops(network, nick.casefold(), user):
                        bot.write(['MODE', trigger.sender, "+o", nick])
                    else:
                        bot.say("{0} isn't in the {1} allowed ops list".format(nick, channel_.get_channel_name()),
                                trigger.nick)
                else:
                    if channel_.is_allowed_ops(network, nick.casefold(), user):
                        bot.write(['MODE', trigger.sender, "-o", nick])
                    else:
                        bot.say("{0} isn't in the {1} allowed ops list".format(nick, channel_.get_channel_name()),
                                trigger.nick)

        elif commands[0].casefold() == 'add':
            commands.pop(0)
            if len(commands) > 0:
                nick = commands[0]
                if nick in channel.users:
                    user = channel.users[nick].user
                    hostmask = channel.users[nick].hostmask.casefold()
                else:
                    bot.say("{0} is not in channel {1}".format(nick, channel_.channel_name))
                    return

            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say("You are not an op in {0}".format(channel_.get_channel_name()), trigger.nick)
                return

            if on_undernet:
                valid_nick: bool = False
                regex = re.compile("(.+)!(.+)@(.+)\.(.+\..+\..+)")
                regex_match = regex.match(hostmask)
                if regex_match:
                    if regex_match.lastindex >= 4:
                        nick = regex_match.group(1)
                        user = regex_match.group(3)
                        valid_nick = regex_match.group(4).find('users.undernet.org') >= 0

                if valid_nick:
                    channel_.add_allowed_op(network, nick.casefold(), user)
                    if vlevel >= V_NORMAL:
                        bot.say("Added {0} to {1} operator list".format(nick, channel_.get_channel_name()))
                else:
                    # we don't have the vhost for the user
                    pending_ops.add_pending_allow_op(network, nick.casefold(), channel_.get_channel_name())
                    bot.write(['PRIVMSG', 'X', ':VERIFY ', nick])
            else:
                channel_.add_allowed_op(network, nick.casefold(), nick.casefold())
                if vlevel >= V_NORMAL:
                    bot.say("Added {0} to {1} operator list".format(nick, channel_.get_channel_name()))

        elif commands[0].casefold() == 'del':
            commands.pop(0)
            if len(commands) > 0:
                nick = commands[0]

            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say("You are not an op in {0}".format(channel_.get_channel_name()), trigger.nick)
                return
            ops_list: list[str] = channel_.get_allowed_ops(network)
            if nick.casefold() in ops_list:
                channel_.del_allowed_op(network, nick.casefold())
                if vlevel > V_NORMAL:
                    bot.say("{0} removed from {1} operator list".format(nick, channel_.get_channel_name()))

        elif commands[0].casefold() == 'list':
            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say("You are not an op in {0}".format(channel_.get_channel_name()), trigger.nick)
                return
            allowed_ops: list[str] = channel_.get_allowed_ops(network)
            if len(allowed_ops) == 0:
                bot.say("No allowed ops", trigger.nick)
            else:
                allowed_ops.sort()
                slice_start : int = 0
                slice_end : int =  5
                while slice_start < len(allowed_ops):
                    if slice_end > len(allowed_ops):
                        slice_end = len(allowed_ops)
                    bot.say('{1} ao list: {0}'.format(', '.join(allowed_ops[slice_start : slice_end]),
                                                      channel_.get_channel_name()), trigger.nick)
                    slice_start = slice_end
                    slice_end += slice_start + 5;
        else:
            bot.say("I don't understand: {0}".format(trigger), trigger.nick)


@plugin.require_privilege(plugin.OP, "Sorry, you must be a channel operator")
@plugin.require_bot_privilege(plugin.OP, 'Please op me')
@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('autovoice', 'av')
@plugin.example('.av nick', 'adds or removes nick')
@plugin.example('.av', "shows all autovoiced people")
@plugin.output_prefix('[av] ')
def on_autovoice(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """  handle the autovoice, like aoutvoice nick
    :param bot:  instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    if trigger.sender in bot.channels:
        channel = bot.channels[trigger.sender]
        channel_key: str = trigger.sender.strip('#&').casefold()
        if channel.has_privilege(trigger.nick, plugin.OP):
            if bot.has_channel_privilege(trigger.sender, plugin.OP):
                args: list[str] = trigger.split()
                args.pop(0)
                if len(args) > 0:
                    while len(args):
                        nick: str = args.pop(0).strip()
                        if nick in channel.users:
                            is_autovoiced: bool = channel_data[channel_key].autovoice.has_user(nick)
                            if not channel.has_privilege(nick, plugin.VOICE):
                                bot.write(['MODE', trigger.sender, "+v", nick])
                                if not is_autovoiced:
                                    bot.say("{0} sets autovoice for {1}".format(trigger.nick, nick))
                                    channel_data[channel_key].autovoice.add_user(str(nick))
                                else:
                                    bot.say("{0} {1} already autovoiced".format(trigger.nick, nick))
                            else: #user is voiced
                                    bot.write(['MODE', trigger.sender, "-v", nick])
                                    if is_autovoiced:
                                        bot.say("{0} clears autovoice for {1}".format(trigger.nick, nick))
                                        channel_data[channel_key].autovoice.remove_user(str(nick))
                else:
                    av_list: list[str] = channel_data[channel_key].autovoice.list_users()
                    if len(av_list) == 0:
                        av_list.append("no nicks are voiced", trigger.nick)
                    else:
                        bot.say('All auto-voiced users in {0}'.format(channel_data[channel_key].get_channel_name()),
                                trigger.nick)
                        show_results(bot, '{0}', 8, av_list, trigger.nick)
                        bot.say('--- end of auto voice list ---', trigger.nick)

@plugin.event('NICK')
@plugin.thread(True)
@plugin.unblockable
@plugin.priority('medium')
def on_nick(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ watch for nick changes"""
    old = trigger.nick
    new = bot.make_identifier(trigger)
    for chankey in channel_data.keys():
        channel_data[chankey].update_idle_nicks(bot, old, new)

@plugin.event('NOTICE')
@plugin.priority('low')
@plugin.output_prefix('[notice] ')
def on_notice(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ handle a user joining the channel
    :param bot:  instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    global pending_ops
    sender: str = trigger.sender
    notice: str = trigger

    if 'X' == sender:
        x_logged_in = re.fullmatch("(.+)!(.+)@(.+) is logged in as (.+)", trigger)
        if x_logged_in:
            # matched user is logged in to X
            nick = x_logged_in.group(1)
            user = x_logged_in.group(4)

            json_str = pending_ops.fetch_pending_allow_ops(bot.config.core.host, nick.casefold())
            if json_str != '':
                pending: dict = json.loads(json_str)
                cname: str = pending['channel']
                ckey = cname.strip('#&').casefold()
                cdata: ChannelData = channel_data[ckey]
                cdata.add_allowed_op(bot.config.core.host, nick.casefold(), user)
                if cdata.get_verbosity() > V_NORMAL:
                    bot.say("Added {0} to {1} operator list".format(nick, cname), cname)
                return

            json_str = pending_ops.fetch_pending_give_ops(bot.config.core.host, nick.casefold())
            if json_str != '':
                pending: dict = json.loads(json_str)
                cname: str = pending['channel']
                user_test = pending['user']
                ckey = cname.strip('#&').casefold()
                cdata: ChannelData = channel_data[ckey]
                if cdata.is_allowed_ops(bot.config.core.host, nick.casefold(), user):
                    channel = bot.channels[cname]
                    if not channel.has_privilege(nick, plugin.OP):
                        bot.write(['MODE', channel.name, "+o", nick])
                return
        else:
            x_not_logged_in = re.fullmatch("(.+)!(.+)@(.+) is NOT logged in.", trigger)
            if x_not_logged_in:
                nick = x_not_logged_in.group(1)
                json_str = pending_ops.fetch_pending_allow_ops(bot.config.core.host, nick.casefold())
                if json_str != '':
                    pending: dict = json.loads(json_str)
                    cname: str = pending['channel']
                    ckey = cname.strip('#&').casefold()
                    cdata: ChannelData = channel_data[ckey]
                    bot.say('{0}: {1} is not logged in to X.'.format(cdata.get_channel_name(), nick),
                            cdata.get_channel_name())
                return
    else:
        print(f'{sender}: {notice}')

#@plugin.interval(30)
#@plugin.output_prefix('[autovoice] ')
#def check_autovoice_callback(bot: sopel.bot.SopelWrapper):
#    """ Interval callback, set at one second
#    :param bot: instance of the sopel bot
#    :type bot: sopel.bot.SopelWrapper
#    """
#    for channel_ in channel_data:
#        channel_data[channel_].autovoice.check_users(bot)
#        channel_data[channel_].autovoice.write_users()

@plugin.event('JOIN')
@plugin.priority('medium')
@plugin.output_prefix('[join] ')
def on_join(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ handle a user joining the channel
    :param bot:  instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    if trigger.sender in bot.channels:
        if not bot.nick in trigger.nick:
            this_channel = bot.channels[trigger.sender]
            key: str = trigger.sender.strip('#&').casefold()
            vlevel: int = channel_data[key].get_verbosity()
            nick: str = trigger.nick
            if vlevel >= V_CHATTY:
                bot.say("{0} welcomes {1}".format(key, nick))
            if bot.has_channel_privilege(trigger.sender, plugin.OP):
                if this_channel.has_privilege(nick, plugin.OP):
                    if vlevel >= V_QUIET:
                        bot.say('welcome op: {0}'.format(nick))
                    return
                else:
                    channel_data[key].update_nick_idle(bot, str(nick))
                    if not this_channel.has_privilege(nick, plugin.VOICE):
                        #t = threading.Timer(2.0, DoAutoVoice, (key, nick, bot), None)
                        #t.start()
                        if channel_data[key].autovoice.has_user(str(nick)):
                            if not this_channel.has_privilege(nick, plugin.VOICE):
                                bot.write(['MODE', trigger.sender, "+v", nick])


@plugin.event('PART')
@plugin.priority('medium')
@plugin.thread(True)
@plugin.output_prefix('[part] ')
def on_part(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """
    handle a user parting the channel
    :param bot: sopel.bot.SopelWrapper
    :param trigger: sopel.trigger
    :return:
    """
    channel = bot.channels[trigger.sender]
    key: str = trigger.sender.strip('#&').casefold()
    channel_data[key].remove_idle_user(bot, str(trigger.nick))
    if channel_data[key].autovoice.has_user(str(trigger.nick)):
        channel_data[key].autovoice.set_nick_time(str(trigger.nick), datetime.datetime.now())
    #t = threading.Timer(2.0, DoUnAutoVoice, (key, trigger.nick, bot), None)
    #t.start()
    vlevel: int = channel_data[key].get_verbosity()
    if vlevel >= V_CHATTY:
        bot.say("{0} waves bye to {1}".format(channel.name.strip('#&'), trigger.nick))


@plugin.event('QUIT')
@plugin.priority('medium')
@plugin.thread(True)
@plugin.output_prefix('[part] ')
def on_quit(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """
    handle a user parting the channel
    :param bot: sopel.bot.SopelWrapper
    :param trigger: sopel.trigger
    :return:
    """
    interval: float = 1.0
    for key in channel_data:
        #t = threading.Timer(interval, DoUnAutoVoice, (key, trigger.nick, bot), None)
        #t.start()
        #interval += 0.2
        if channel_data[key].autovoice.has_user(str(trigger.nick)):
            channel_data[key].autovoice.set_nick_time(str(trigger.nick), datetime.datetime.now())


@plugin.event('PRIVMSG')
@plugin.priority('medium')
@plugin.thread(True)
@plugin.output_prefix('[privmsg] ')
def on_privmsg(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ handle a message in a channel
    :param bot:  instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    if trigger.sender in bot.channels:
        if not bot.nick in trigger.nick:
            this_channel = bot.channels[trigger.sender]
            nick: str = trigger.nick
            channel_name: str = this_channel.name
            text: str = trigger
            ckey: str = this_channel.name.strip("#&").casefold()
            channel_ = channel_data[ckey]
            channel_.update_nick_idle(bot, nick)
            #t = threading.Timer(1.0, DoAutoVoice, (ckey, nick, bot), None)
            #t.start()
            if channel_data[ckey].autovoice.has_user(str(trigger.nick)):
                channel_data[ckey].autovoice.set_nick_time(str(trigger.nick), datetime.datetime.now())
            #print(f'{channel_name} {nick} -> {text}')





@plugin.require_privilege(plugin.OP, "Sorry, you must be a channel operator")
@plugin.require_chanmsg('Please run this command in the channel')
@plugin.command('announce', 'ann')
@plugin.example('!announce on delay 15m', 'sets the announce message for display every 15 minutes')
@plugin.example('!ann', 'toggles the display of the anouncement message')
#@plugin_example('!ann set Type !rules to see the channel rules', 'sets the annoucement message')
@plugin.output_prefix('[announce] ')
def on_announce(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """
    enable or disable the channel announcement
    :param bot: sopel.bot.SopelWrapper
    :param trigger: sopel.trigger
    :return:
    """
    on: bool = False
    toggle: bool = True;
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]
    vlevel: int = channel_.get_verbosity()
    announcement : Announcement = channel_.get_announcement()
    command: list[str] = trigger.split()
    command.pop(0)  # remove command
    image_keys: list[int] = []
    on: bool = False
    toggle: bool = True;
    announce_message: str = ''
    delay: int = 15*60
    while len(command):
        option: str = command.pop(0).lower()
        if "on" in option:
            on = True
            toggle = False
            announcement.set_announce_enabe(on)
            bot.say('announcement is now on')
        elif 'off' in option:
            on = False
            toggle = False
            announcement.set_announce_enabe(on)
            bot.say('announcement is now off')
        elif 'delay' in option:
            multiplier = 1
            # check for specified delay 10, 10s, 10m
            if len(command):
                value: str = command.pop(0).lower()
                delay = fetch_delay(value)
                if delay < 0:
                    bot.say(f"I don't understand a delay of {value}, ignoring announcement request")
                    return
                announcement.set_annouce_delay(delay)
                bot.say(f'annoucement repeats every {delay} seconds')
                toggle = False
        elif 'set' in option:
            if len(command):
                announce_message: str = ' '.join(command)
                announcement.set_annouce_message(announce_message)
                bot.say(f'annoucement set to: {announce_message}')
                toggle = False
                command.clear()
    if toggle:
        announcement.set_announce_enabe(not announcement.get_announce_enable())
        if announcement.get_announce_enable():
            bot.say('announcement is now on')
        else:
            bot.say('announcement is now off')


@plugin.interval(PLUGIN_INTERVAL)
@plugin.output_prefix('[announce] ')
def announce_callback(bot: sopel.bot.SopelWrapper):
    for channel_key in list(channel_data.keys()):
        channel = channel_data[channel_key]
        announcement: Announcement = channel.get_announcement()
        if announcement.get_announce_enable():
            if announcement.should_announce():
                announcement.make_announcement(bot)



@plugin.require_chanmsg('channel only command')
@plugin.command('add')
@plugin.example('add <url> [key1,key2,key3...]', 'adds the url and amy associated keys')
@plugin.output_prefix('[add] ')
def on_add_image(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ add an image to the channel's image dictionary
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]
    vlevel: int = channel_.get_verbosity()
    commands: list[str] = trigger.split()
    commands.pop(0)

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "add"):
        bot.say('{0} is not permitted in {1}'.format('add', channel_.get_channel_name()))
        return

    if len(commands):
        id_: int = -1
        url = commands.pop(0)
        parsed_url: parse.ParseResult = parse.urlparse(url);
        url_string: str = ''
        if parsed_url.netloc.find('uguu.') > -1:
            url_string = f'temporary url {url} not allowed'
        elif (parsed_url.netloc.find('reblogme.') > -1) or (parsed_url.netloc.find('bdsmlr.') > -1):
            url_string = f'reblogme and bdsmlr no longer permit sharing (Error 403 Forbidden)'
        elif parsed_url.query.find('secure=') > -1:
            url_string = f'Secure url {url} not allowed'
        else:
            id_ = channel_.image_dictionary.find_image(url)
            if id_:
                url_string = "url exists id={0}".format(id_)
            else:
                id_ = channel_.image_dictionary.add_image(url)
                url_string = "url added id={0}".format(id_)
        if id_ > 0:
            image: Image = channel_.image_dictionary.get_image(id_)
            added_keys: list[str] = []
            while len(commands):
                key_list = commands[0].split(',')
                for key in key_list:
                    key = parse.unquote_plus(key.strip())
                    if key:
                        cat_id = channel_.category_dictionary.add_category(key)
                        image.add_category(cat_id,1)
                        added_keys.append(key)
                commands.pop(0)
            LOGGER.info(f'{trigger.sender} ADD_URL {id_}: {url} ({",".join(added_keys)}) by {trigger.nick}')
            if vlevel >= V_QUIET:
                bot.say('{1}: {0}'.format(','.join(added_keys), url_string))
        else:
            bot.say(url_string)
    else:
        bot.say('missing arguments')

@plugin.require_chanmsg('channel only command')
@plugin.command('get')
@plugin.output_prefix('[get] ')
def on_get(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ fetch a random image or fetch an image based on it's id
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_: ChannelData = channel_data[channel_key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "get"):
        bot.say('{0} is not permitted in {1}'.format('get', channel_.get_channel_name()))
        return

    image_id: int = -1
    image: Image = None
    command.pop(0)  # !get
    image_keys: list[int] = list(channel_.image_dictionary)
    #any images in this channel?
    if len(image_keys) == 0:
        bot.say('Sorry, no images in {0}'.format(channel.name))
        return
    image_keys.sort()
    # if we have an argument it is either a image_id or the word "key"
    keyword_search = False
    if len(command):
        if 'key' in command[0]:
            command.pop(0)  # key
            keyword_search = True
            if len(command):
                keywords: list[str] = command.copy()
                image_keys = match_categories(channel_, keywords)
                if len(image_keys) > 0:
                    image_id = random.choice(image_keys)
                    image = channel_.image_dictionary.get_image(image_id)
                else:
                    bot.say("no images match keywords: {0}".format(' '.join(command)))
            else:
                bot.say('Oops: No keyword(s) specifed for the key')
        else:
            # get image for image id
            try:
                if command[0].isdigit():
                    image_id: int = int(command[0])
                    image_keys = list(channel_.image_dictionary)
                    if image_id in image_keys:
                        image = channel_.image_dictionary.get_image(image_id)
                    else:
                        if image_id > 0:
                            bot.say("Sorry, I don't have an image with id: {0}".format(image_id))
                else:
                    keyword_search = True
                    keywords: list[str] = command.copy()
                    image_keys = match_categories(channel_, keywords)
                    if len(image_keys) > 0:
                        image_id = random.choice(image_keys)
                        image = channel_.image_dictionary.get_image(image_id)
                    else:
                        bot.say("no images match keywords: {0}".format(' '.join(command)))
            except:
                bot.say("{0} is not a valid number".format(command[0]))
    else:
        # get random image
        image_id = random.choice(image_keys)
        image = channel_.image_dictionary.get_image(image_id)

    if not image:
        if not keyword_search:
            bot.say("Try an id between {0} and {1} ({2} entries)".format(
                image_keys[0], image_keys[len(image_keys) - 1], len(image_keys)))
    else:
        url = image.get_url()
        bot.say('{0}: {1}'.format(image_id, url))


@plugin.require_privilege(plugin.OP, "Sorry, you must be a channel operator")
@plugin.require_chanmsg('channel only command')
@plugin.commands('keywords', 'keys')
@plugin.output_prefix('[keys] ')
def on_keywords(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ show keywords that match the user input
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    command.pop(0)
    if len(command):
        channel = bot.channels[trigger.sender]
        key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[key]

        # test for feature enable
        if not channel_.is_command_enabled(bot, trigger, "keywords"):
            bot.say('{0} is not permitted in {1}'.format('keywords', channel_.get_channel_name()))
            return

        keywords: list[str] = channel_.category_dictionary.fetch_keywords()
        keywords.sort()
        bot.say("There are {0} category keywords defined".format(len(keywords)), trigger.nick)

        found_keys: list[str] = []
        search_keys: list[str] = []
        while len(command):
            match: list[str] = command[0].split(',')
            search_keys.extend(match)
            command.pop(0)

        search_keys.sort();
        for sk in search_keys:
            for kw in keywords:
                if kw.startswith(sk):
                    if kw not in found_keys:
                        found_keys.append(parse.unquote_plus(kw))
        found_keys.sort()

        slice_size: int = 10
        slice_start : int = 0;
        slice_stop: int = slice_start + slice_size;
        if len(found_keys) == 0:
            bot.say("no keywords found.", trigger.nick)
        else:
            bot.say('There are {0} matching keywords ({1})'.format(len(found_keys), ','.join(search_keys)), trigger.nick)
            show_results(bot, 'keys: {0}', 10, found_keys, trigger.nick)
            bot.say('--- end of keywords ---', trigger.nick)
    else:
        bot.say("no search keys defined", trigger.nick)


@plugin.require_chanmsg('channel only command')
@plugin.command('match')
@plugin.output_prefix('[match] ')
def on_match(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ show keywords that match the user input
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    image_id: int = -1
    keyword: str = ''
    keywords: list[str] = []
    if len(command) > 1:
        keywords = command[1].split(',')
        channel = bot.channels[trigger.sender]
        key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[key]

        # test for feature enable
        if not channel_.is_command_enabled(bot, trigger, "match"):
            bot.say('{0} is not permitted in {1}'.format('match', channel_.get_channel_name()))
            return

        categories: list[int] = []
        for keyword in keywords:
            cats: list[int] = channel_.category_dictionary.find_matches(parse.unquote_plus(keyword))
            if len(cats):
                cat_list: list[str] = []
                for cat in cats:
                    cat_list.append('\'{0}\''.format(parse.unquote_plus(channel_.category_dictionary.get(cat))))
                bot.say('{0} matches {1} categories'.format(keyword, len(cat_list)), trigger.nick)
                show_results(bot, '{0}', 10, cat_list, trigger.nick)
                bot.say('--- end of matches ---', trigger.nick)
            else:
                bot.say("{0} doesn't have any matches".format(keyword))
    else:
        bot.say("please specify a match string")

@plugin.require_chanmsg('channel only command')
@plugin.command('details', 'peek')
@plugin.output_prefix('[peek] ')
def on_details(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ show details of an image based on id
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    image_id: int = -1
    use_keyword: bool = False
    keyword: str = ''
    if len(command) > 1:
        try:
            image_id: int = int(command[1])
        except:
            bot.say("{0} is not a valid number".format(command[1]))
            return
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "details"):
        bot.say('{0} is not permitted in {1}'.format('details', channel_.get_channel_name()))
        return

    image: Image = channel_.image_dictionary.get_image(image_id)
    if image:
        bot.say('{0}: url: {1}'.format(image_id, image.get_url()))
        categories: Categories = image.get_categories()
        if len(categories):
            cat_list: list[str] = []
            for cat_id,cat_count in categories.items():
                cat_str: str = channel_.category_dictionary.get(cat_id)
                cat_list.append("{0}:{1}".format(cat_str,cat_count))
            bot.say("keys: {0}".format(','.join(cat_list)))
        else:
            bot.say("there are no keys associated with this image")
    else:
        bot.say('I don\'t have an iamge with id = {0}'.format(image_id))


@plugin.require_chanmsg('channel only command')
@plugin.command('show', 'sh')
@plugin.output_prefix('[show] ')
def on_show(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ fetch a random image or fetch an image based on it's id
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "show"):
        bot.say('{0} is not permitted in {1}'.format('show', channel_.get_channel_name()))
        return

    command.pop(0)
    keywords: list[str] = command.copy()
    keys: list[int]  = match_categories(channel_, keywords)
    if len(keys) >= 1:
        image_id: int = random.choice(keys)
        url = channel_.image_dictionary.get_url(image_id)
        bot.say('{0} {1}: {2}'.format(' '.join(command), image_id, url))
    else:
        bot.say("no matches for keyword(s) {0}".format(' '.join(command)))


@plugin.require_chanmsg('channel only command')
@plugin.command('showx', 'shx')
@plugin.output_prefix('[showx] ')
def on_show_exact(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ fetch a random image or fetch an image based on it's id
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "showx"):
        bot.say('{0} is not permitted in {1}'.format('showx', channel_.get_channel_name()))
        return

    command.pop(0)
    keywords: list[str] = command.copy()
    keys: list[int] = match_categories(channel_, keywords, True)
    if len(keys) >= 1:
        image_id: int = random.choice(keys)
        url = channel_.image_dictionary.get_url(image_id)
        bot.say('{0} {1}: {2}'.format(' '.join(command), image_id, url))
    else:
        bot.say("no matches for keyword(s) {0}".format(' '.join(command)))


@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.commands('del', 'delete')
@plugin.output_prefix('[delete] ')
def on_delete(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ delete an image from the dictionary, move it to the deleted images
    dictionary
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    delete_keyword: str = command.pop(0)
    if len(command):
        channel = bot.channels[trigger.sender]
        key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[key]
        keys: list[int] = list(channel_.image_dictionary)
        while len(command) > 0:
            id_list = command[0].split(',')
            for ids in id_list:
                if ids.isdigit():
                    try:
                        image_id: int = int(ids)
                        if image_id in keys:
                            channel_.image_dictionary.delete_image(image_id)
                            bot.say("Deleted image #{0}".format(image_id))
                        else:
                            bot.say("There is no image with id={0} in {1}".format(image_id, channel.name))
                    except:
                        bot.say("{0} is not a valid number".format(ids))
            command.pop(0)
    else:
        bot.say("delete requires one or more image ids to delete")
    return

#@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('addkeys', 'ak')
@plugin.example('.addkeys 123 shiny,sweet', 'adds keys shiny and sweet to the image id 123')
@plugin.output_prefix('[addkeys] ')
def on_addkeys(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ add keys to an image
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    addkeys_command: str = command.pop(0)
    if len(command):
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]
        # read the image id
        image_id: int = 0
        try:
            image_id = int(command[0])
            command.pop(0)
        except ValueError:
            bot.say('{0} is not a valid number'.format(command[0]))
            return

        # test for feature enable
        if not channel_.is_command_enabled(bot, trigger, "addkeys"):
            bot.say('{0} is not permitted in {1}'.format('addkeys', channel_.get_channel_name()))
            return

        image: Image = channel_.image_dictionary.get_image(image_id)
        if not image is None:
            added_keys: list[str] = []
            while len(command) > 0:
                key_list = command[0].split(',')
                for key in key_list:
                    key = key.strip()
                    if key:
                        cat_id = channel_.category_dictionary.add_category(key)
                        image.add_category(cat_id, 1)
                        added_keys.append(key)
                command.pop(0)
            bot.say ('Added key(s) {0} to image {1}: {2}'.format(','.join(added_keys), image_id, image.get_url()))
        else:
            bot.say('No image exists with ID: {0}'.format(image_id))
    else:
        bot.say("No keywords specified")


@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('delkeys', 'dk')
@plugin.example('.delkeys 123 shiny,sweet', 'deletes keys shiny and sweet from the image id 123')
@plugin.output_prefix('[delkeys] ')
def on_delkeys(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ deletes keys from an image
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    delkeys_command: str = command.pop(0)
    if len(command):
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]
        # read the image id
        image_id: int = 0
        try:
            image_id = int(command[0])
        except ValueError:
            bot.say('{0} is not a valid number'.format(command[0]))
            return
        image: Image = channel_.image_dictionary.get_image(image_id)
        if not image is None:
            command.pop(0)
            deleted_keys: list[str] = []
            while len(command) > 0:
                key_list = command[0].split(',')
                for key in key_list:
                    key = parse.unquote_plus(key.strip())
                    if key:
                        cat_id = channel_.category_dictionary.get_index(key)
                        if cat_id != 0:
                            if image.del_category(cat_id):
                                deleted_keys.append(parse.quote_plus(key))
                command.pop(0)
            bot.say ('Removed key(s) {0} from image {1}: {2}'.format(','.join(deleted_keys), image_id, image.get_url()))
        else:
            bot.say('No image exists with ID: {0}'.format(image_id))
    else:
        bot.say("No keywords specified")


#@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('listids', 'ls', 'find')
@plugin.example('.list shiny,sweet', 'lists all image ids with the keys shiny and sweet')
@plugin.output_prefix('[ls] ')
def on_list(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ add keys to an image
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]
    command: list[str] = trigger.split()

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "listids"):
        bot.say('{0} is not permitted in {1}'.format('listids', channel_.get_channel_name()))
        return

    image_id: int = -1
    keyword: str = ''
    keywords: list[str] = []
    keys: list[int] = []
    first_pass: bool = True
    command.pop(0)
    if len(command) == 0:
        bot.say('No keywords specified')
        return
    bot.say("*** listids ***", trigger.nick)
    while len(command):
        categories: list[int] = []
        keywords = command[0].split(',')
        for keyword in keywords:
            cats: list[int] = channel_.category_dictionary.find_matches(parse.unquote_plus(keyword.lower()))
            for cat in cats:
                categories.append(cat)
        if first_pass:
            keys: list[int] = channel_.image_dictionary.find_matches(categories)
            if len(keys):
                bot.say('key(s): {0}:'.format(','.join(keywords)), trigger.nick)
                show_results(bot, 'ids: {0}', 10, keys, trigger.nick)
            else:
                bot.say('key(s):{0}, no image match the key(s)'.format(','.join(keywords)), trigger.nick)
            first_pass = False
        else:
            filter_keys: list[int] = channel_.image_dictionary.find_matches(categories)
            remove_keys: list[int] = []
            for key in keys:
                if key not in filter_keys:
                    remove_keys.append(key)
            for key in remove_keys:
                keys.remove(key)
            if len(keys):
                bot.say('filter key(s): {0}:'.format(','.join(keywords)), trigger.nick)
                show_results(bot, 'ids: {0}', 10, keys, trigger.nick)
            else:
                bot.say('filter key(s):{0}, no image match the key(s)'.format(','.join(keywords)), trigger.nick)
        command.pop(0)
        if len(keys) == 0:
            break
    bot.say(' ---end listids---', trigger.nick)


@plugin.require_chanmsg('channel only command')
@plugin.command('listidsx', 'lsx', 'findx', 'lx')
@plugin.example('.list shiny,sweet', 'lists all image ids with the keys shiny and sweet')
@plugin.output_prefix('[lsx] ')
def on_listx(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ add keys to an image
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]
    command: list[str] = trigger.split()

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "listidsx"):
        bot.say('{0} is not permitted in {1}'.format('listidsx', channel_.get_channel_name()))
        return

    image_id: int = -1
    keyword: str = ''
    keywords: list[str] = []
    keys: list[int] = []
    first_pass: bool = True
    command.pop(0)
    if len(command) == 0:
        bot.say('No keywords specified')
        return
    bot.say("*** listidsx ***", trigger.nick)

    while len(command):
        categories: list[int] = []
        keywords = command[0].split(',')
        for keyword in keywords:
            cats: list[int] = channel_.category_dictionary.find_matches_exact(parse.unquote_plus(keyword.casefold()))
            for cat in cats:
                categories.append(cat)
        if first_pass:
            keys: list[int] = channel_.image_dictionary.find_matches(categories)
            if len(keys):
                bot.say('key(s): {0}:'.format(','.join(keywords)), trigger.nick)
                show_results(bot, 'ids: {0}', 10, keys, trigger.nick)
            else:
                bot.say('key(s):{0}, no image match the key(s)'.format(','.join(keywords)), trigger.nick)
            first_pass = False
        else:
            filter_keys: list[int] = channel_.image_dictionary.find_matches(categories)
            remove_keys: list[int] = []
            for key in keys:
                if key not in filter_keys:
                    remove_keys.append(key)
            for key in remove_keys:
                keys.remove(key)
            if len(keys):
                bot.say('filter key(s): {0}:'.format(','.join(keywords)), trigger.nick)
                show_results(bot, 'ids: {0}', 10, keys, trigger.nick)
            else:
                bot.say('filter key(s):{0}, no image match the key(s)'.format(','.join(keywords)), trigger.nick)
        command.pop(0)
        if len(keys) == 0:
            break
    bot.say(' ---end listidsx---', trigger.nick)

class ImageMerge:
    def __init__(self):
        self.enabled: bool = False
        self.busy: bool = False
        self.merge_channels: dict[str, list[str]] = {}
        self.merge_counts: dict[str, (int, int)] = {}
        self.mutex: threading.Lock = threading.Lock()

    def set_add_commands(self, key: str, add_commands: list[str]):
        with self.mutex:
            if key in self.merge_channels:
                self.merge_channels[d] = self.merge_channels[d] + add_commands
                self.merge_counts[d][0] += len(add_commands)

            else:
                self.merge_channels[key] = add_commands
                self.merge_counts[key] = (len(add_commands), 0)
            self.enabled = True

    def do_add_command(self, bot: sopel.bot.SopelWrapper, key: str, add_cmd: str ):
        commands: list[str] = add_cmd.split()
        commands.pop(0)
        if len(commands):
            channel_ = channel_data[key]
            channel_name = channel_.get_channel_name()
            id_: int = -1
            url = commands.pop(0)
            parsed_url: parse.ParseResult = parse.urlparse(url);
            url_string: str = ''
            if parsed_url.netloc.find('uguu.') > 0:
                url_string = f'temporary url {url} not allowed'
            elif parsed_url.query.find('secure=') > 0:
                url_string = f'Secure url {url} not allowed'
            else:
                id_ = channel_.image_dictionary.find_image(url)
                if id_:
                    url_string = "url exists id={0}".format(id_)
                else:
                    id_ = channel_.image_dictionary.add_image(url)
                    url_string = "url added id={0}".format(id_)
            if id_ > 0:
                image: Image = channel_.image_dictionary.get_image(id_)
                added_keys: list[str] = []
                while len(commands):
                    key_list = commands[0].split(',')
                    for key in key_list:
                        key = parse.unquote_plus(key.strip())
                        if key:
                            cat_id = channel_.category_dictionary.add_category(key)
                            image.add_category(cat_id, 1)
                            added_keys.append(key)
                    commands.pop(0)
                chan_name = channel_.get_channel_name()
                LOGGER.info(f'{chan_name} MERGE_URL {id_}: {url} ({",".join(added_keys)}) by {bot.nick}')
                (t,c) = self.merge_counts[key]
                c += 1
                self.merge_counts = (t,c)
                if (c % 100) == 0:
                    percent = (c * 100) / t
                    bot.say(f'merge {percent}% complete', channel_name)
            else:
                (t,c) = self.merge_counts[key]
                c += 1
                self.merge_counts = (t,c)
                if (c % 100) == 0:
                    percent = (c * 100) / t
                    bot.say(f'merge {percent}% complete', channel_name)

    def handle_callback(self, bot: sopel.bot.SopelWrapper):
        if self.busy:
            return
        with self.mutex:
            if (self.enabled):
                self.busy = True
                if len(self.merge_channels) == 0:
                    self.enabled = False
                    return
                for key in self.merge_channels.keys():
                    adds = self.merge_channels[key]
                    if len(adds):
                        this_add = adds.pop(0)
                        #bot.say(this_add, channel_data[key].get_channel_name())
                        self.do_add_command(bot, key, this_add)
                    else:
                        del self.merge_channels[key]
                        chan_name = channel_data[key].get_channel_name()
                        bot.say(f'{chan_name}: Merge complete', chan_name)
                self.busy = False

imageMerge: ImageMerge = ImageMerge();

@plugin.interval(2)
@plugin.output_prefix('[merge] ')
def image_merge_callback(bot: sopel.bot.SopelWrapper):
    imageMerge.handle_callback(bot)

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('merge')
@plugin.example('merge /path/to/add_channel_commands.txt', 'lists all image ids with the keys shiny and sweet')
def on_merge(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ Merge the add commands into the current image dictionary and categories """
    channel = bot.channels[trigger.sender]
    chan_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[chan_key]
    command: list[str] = trigger.split()
    list_command: str = command.pop(0)
    if len(command):
        filespec: str = command.pop()
        if os.path.exists(filespec) and os.path.isfile(filespec):
            with io.open(filespec, 'r', encoding="utf-8") as f_adds:
                imageMerge.set_add_commands(chan_key, f_adds.readlines())
            bot.say(f'{channel.name}: Merge in Progress')

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('restore')
@plugin.example('restore id[,id,id...]', 'lists all image ids with the keys shiny and sweet')
@plugin.output_prefix('[restore] ')
def on_restore(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ restore an image
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    # capture channel
    channel = bot.channels[trigger.sender]
    chan_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[chan_key]
    # process command
    command: list[str] = trigger.split()
    list_command: str = command.pop(0)
    if len(command):
        deleted_list = channel_.image_dictionary.fetch_deleted_ids()
        while len(command):
            image_ids: list[int] = []
            id_list: list[str] = command[0].split(',')
            id_: int = 0
            for id_str in id_list:
                try:
                    id_ = int(id_str)
                except Exception:
                    bot.say('{0} isn\'t an integer'.format(id_str))
                    continue
                if id_ in deleted_list:
                    restored_id: int = channel_.image_dictionary.restore_image(id_)
                    bot.say("Image at id {0} restored as id {1}".format(id_,restored_id))
                else:
                    bot.say("No deleted image exists with id = {0}".format(id_))
            command.pop(0)
    else:
        bot.say('No deleted image id specified')


#@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('listdel', 'ld')
@plugin.example('.ld', 'lists all image ids that have been deleted')
@plugin.example('.ld id1,id2,...', 'lists the image url for the deleted id deleted')
@plugin.output_prefix('[ld] ')
def on_list_deleted(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ show deleted images
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    # determine channel
    channel = bot.channels[trigger.sender]
    chan_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[chan_key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "listdel"):
        bot.say('{0} is not permitted in {1}'.format('listdel', channel_.get_channel_name()))
        return
    # handle command
    command: list[str] = trigger.split()
    list_command: str = command.pop(0)
    if len(command):
        while len(command):
            image_ids: list [int] = []
            id_list: list[str] = command[0].split(',')
            for id_str in id_list:
                try:
                    id_: int = int(id_str)
                    url_: str = channel_.image_dictionary.fetch_deleted_url(id_)
                    bot.say('id: {0} url: {1}'.format(id_, url_))
                except Exception:
                    bot.say('{0} isn\'t an integer'.format(id_str))
            command.pop(0)
    else:
        bot.say("*** listdel ***", trigger.nick)
        id_list: list[int] = channel_.image_dictionary.fetch_deleted_ids()
        bot.say('Deleted ids in {0}'.format(channel_.get_channel_name()), trigger.nick)
        show_results(bot, ' {0}', 10, id_list, trigger.nick)
        bot.say(' ---end listdel---', trigger.nick)

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('purgekey', 'purge')
@plugin.example('.purgekey key,key', 'removes key if not used')
@plugin.output_prefix('[purge] ')
def on_purge(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ purge keys from the category file
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    purge_command: str = command.pop(0)
    if len(command):
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]
        while len(command) > 0:
            key_list = command[0].split(',')
            command.pop(0)
            for key in key_list:
                key = key.strip()
                cat_id = channel_.category_dictionary.get_index(parse.unquote_plus(key))
                if cat_id > 0:
                    image_ids: list[int] = channel_.image_dictionary.find_matches([cat_id])
                    if len(image_ids) == 0:
                        channel_.category_dictionary.delete_category(cat_id)
                        bot.say("removed {0} from key dictionary".format(key))
                    else:
                        bot.say("{0} is used in the image dictionary".format(key))
                else:
                    bot.say("{0} in not in the key dictionary".format(key))
    else:
        bot.say("No keyword specified".format(key))

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('renumber', 'ren')
@plugin.example('!renumber', 'renumbers image links and flushes to backing store')
@plugin.output_prefix('[renumber] ')
def on_renumber(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ checkpoint the categories and images for the current channel
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    checkpoint_command: str = command.pop(0)
    if len(command) == 0:
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]
        image_count: int  = channel_.image_dictionary.renumber_images();
        bot.say('{0}: {1} {2} images renumbered and saved.'.format(channel.name,trigger.nick, image_count))
    else:
        bot.say('{0}: {1} command ignored, too many parameters.'.format(channel.name, trigger.nick))

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('checkpoint', 'cp')
@plugin.example('!checkpoint', 'flushes the keywords and image links to backing store')
@plugin.output_prefix('[checkpoint] ')
def on_checkpoint(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ checkpoint the categories and images for the current channel
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    checkpoint_command: str = command.pop(0)
    if len(command) == 0:
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]
        channel_.checkpoint();
        bot.say('{0}: {1} keywords and image <urls> saved.'.format(channel.name,trigger.nick))
    else:
        bot.say('{0}: {1} command ignored, too many parameters.'.format(channel.name, trigger.nick))


@plugin.interval(PLUGIN_INTERVAL)
@plugin.output_prefix('[autoplay] ')
def autoplay_callback(bot: sopel.bot.SopelWrapper):
    """ Interval callback, set at one second
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    """
    if len(channel_data.keys()):
        channel_keys = channel_data.keys()
        for channel_key in channel_keys:
            channel = channel_data[channel_key]
            if channel.autoplay.get_autoplay_state():
                if channel.autoplay.show_next_image():
                    #if not channel.autoplay.has_image_keys():
                    #    channel.autoplay.set_image_keys(list(channel.image_dictionary.keys()))
                    if channel.autoplay.has_image_keys():
                        image_id = channel.autoplay.fetch_next_id()
                        if image_id > 0:
                            url: str = channel.image_dictionary.get_url(image_id)
                            bot.say('id={0}: {1}'.format(image_id, url), channel.get_channel_name())
                        else:
                            bot.say("autoplay complete", channel.get_channel_name())
                    else:
                        bot.say('<no images>:', channel.get_channel_name())
                        channel.autoplay.set_autoplay(False)
                if channel.gameplay.get_game_mode():
                    channel.gameplay.process_clocktick(bot, channel_key)


@plugin.require_chanmsg('channel only command')
@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.commands('auto', 'autoplay')
@plugin.output_prefix('[autoplay] ')
def on_autoplay(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ fetch random images based on a delay or turn autoplay off
    auto[play] [off [ [on] [delay <int>[m|s] [key <str>] ]
    auto[play] (toggles autoplay)
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "autoplay"):
        bot.say('{0} is not permitted in {1}'.format('autoplay', channel_.get_channel_name()))
        return

    delay: int = 60
    toggle: bool = True
    on: bool = False
    sequential: bool = False
    count_up: bool = True
    loop: bool = False
    begin_id: int= -1
    end_id: int = -1
    keyword_search: bool = False
    keywords: list[str] = []
    command: list[str] = trigger.split()
    command.pop(0) # remove command
    image_keys: list[int] = []
    while len(command):
        option: str = command.pop(0).lower()
        if "on" in option:
            on = True
            toggle = False
        elif 'off' in option:
            on = False
            toggle = False
        elif 'seq' in option:
            sequential = True
        elif 'bid' in option:
            if len(command):
                try:
                    begin_id = int(command.pop(0))
                except ValueError:
                    bot.say("I don't start_id of {0}, ignoring autoplay request".format(command[0]))
                    return
            else:
                start_id = -1
        elif 'eid' in option:
            if len(command):
                try:
                    end_id = int(command.pop(0))
                except ValueError:
                    bot.say("I don't start_id of {0}, ignoring autoplay request".format(command[0]))
                    return
            else:
                end_id = -1
        elif 'up' in option:
            count_up = True
        elif 'down' in option:
            count_up = False
        elif 'loop' in option:
            loop = True
        elif 'delay' in option:
            multiplier = 1
            # check for specified delay 10, 10s, 10m
            if len(command):
                value: str = command.pop(0).lower()
                delay = fetch_delay(value)
                if delay < 0:
                    bot.say(f"I don't understand a delay of {value}, ignoring autoplay request")
                    return
        elif 'key' in option:
            keyword_search = True
            if len(command):
                keywords = command.copy()
                image_keys = match_categories(channel_,keywords)
                image_keys.sort()
                if len(image_keys) == 0:
                    bot.say("no images for keyword search {0}".format(' '.join(command)))
            else:
                bot.say("No keywords specified for {0}".format(option))
            # we consume all the keywords
            break
        else:
            bot.say(f"No option {option}, example: !auto on delay 3m key sun,moon")

    if toggle:
        on = not channel_.autoplay.get_autoplay_state()

    if on:
        if not keyword_search:
            image_keys = list(channel_.image_dictionary)
            image_keys.sort()
            begin_index = 0
            end_index = len(image_keys)
            if begin_id in image_keys:
                begin_index = image_keys.index(begin_id)
            if end_id in image_keys:
                end_index = image_keys.index(end_id)+1
            if begin_index > end_index:
                x = begin_index
                begin_index = end_index-1
                end_index = x+1
            if (begin_index != 0) or (end_index != len(image_keys)):
                image_keys = image_keys[begin_index:end_index]
        on = len(image_keys) > 0
    if on:
        channel_.autoplay.set_autoplay(True, delay, sequential, count_up, loop, image_keys)
        on: str = formatting.color("on", formatting.colors.GREEN)
        bot.say("autoplay {2} in {0}, delay = {1} seconds".format(channel.name, delay, on))
    else:
        channel_.autoplay.set_autoplay(False)
        off: str = formatting.color("off", formatting.colors.RED)
        bot.say("autoplay {1} in {0}".format(channel.name, off))


@plugin.interval(PLUGIN_INTERVAL)
@plugin.output_prefix('[game] ')
def gameplay_callback(bot: sopel.bot.SopelWrapper):
    """ Interval callback, set at one second
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    """
    if len(channel_data.keys()):
        channel_keys = channel_data.keys()
        for channel_key in channel_keys:
            channel = channel_data[channel_key]
            if channel.gameplay.get_game_mode():
                channel.gameplay.process_clocktick(bot, channel_key)

# morris: add start stop reset
# update help

#@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.commands('game')
@plugin.output_prefix('[game] ')
def on_game(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    global game_dict
    """ start the game
        check if autoplay is on and disable it
        disable the get command
        disable the del command
        notify the channel that we are in game mode
        .game start number_of_images [auto] [delay]
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]
    oper: str = formatting.color(formatting.bold(trigger.nick), formatting.colors.BLUE)

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "game"):
        bot.say('{0} is not permitted in {1}'.format('game', channel_.get_channel_name()))
        return

    #
    # command defaults
    #
    set_opened: bool = False
    set_closed: bool = False
    reset_scores: bool = False
    toggle: bool = True
    on: bool = False
    off: bool = False
    help: bool = False
    auto: bool = False
    delay: int = 30
    pause: int = 15
    rounds: int = 5
    #
    # process command arguments
    #
    command: list[str] = trigger.split()
    command.pop(0)
    while len(command):
        option: str = command.pop(0).lower()
        if ('on' in option) or ('start' in option):
            toggle = False
            on = True
            off = False
            auto = False
            reset_scores = False

        elif ('off' in option) or ('stop' in option):
            toggle = False
            off = True
            on = False
            auto = False
            reset_scores = False

        elif 'open' in option:
            set_opened = True

        elif 'close' in option:
            set_closed = True

        elif 'help' in option:
            # help will override other options
            help = True

        elif 'reset' in option:
            reset_scores = True

        elif 'auto' in option:
            auto = True
            toggle = False
            on = False
            off = False
            reset_scores = False

        elif 'rounds' in option:
            if len(command):
                try:
                    rounds = int(command.pop(0))
                except ValueError:
                    rounds = 5

        elif 'delay' in option:
            if len(command):
                delay = fetch_delay(command[0])
                if delay < 0:
                    delay = 60
                    bot.say(f'I don\'t understands a delay of {command[0]}, setting to 60 seconds')
                command.pop(0)

        elif 'pause' in option:
            if len(command):
                pause = fetch_delay(command[0])
                if pause < 0:
                    pause = 15
                    bot.say(f'I don\'t understands a pause of {command[0]}, setting to 15 seconds')
                command.pop(0)
        else:
            bot.say("I don't understand {0}, ignoring".format(command.pop(0)))

    # open auto gameplay to users
    if set_opened:
        set_closed = False
        toggle = False
        on = False
        off = False
        help = False
        auto = False

    # close auto gameplay to users
    if set_closed:
        set_opened = False
        toggle = False
        on = False
        off = False
        help = False
        auto = False

    if help:
        toggle = False
        on = False
        off = False
        auto = False
        reset_scores = False

    if off:
        toggle = False
        on = False
        auto = False

    if on:
        toggle = False
        off = False
        auto = False

    if auto:
        toggle = False
        on = False
        off = False

    if reset_scores:
        toggle = False
        on = False
        off = False
        auto = False
        set_opened = False
        ser_closed = False
    #process help
    if help:
        game_cmds : list[str] = game_dict["commands"]
        for line in game_cmds:
            bot.say('{0}'.format(formatting.bold(line)), trigger.nick)

        game_info : list[str] = game_dict["gameplay"]
        for line in game_info:
            bot.say('{0}'.format(formatting.italic(line)), trigger.nick)

    elif set_opened:
        if channel_.gameplay.is_closed():
            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say('Sorry, game play requires and Op, ask an Op to open it.')
                return

        channel_.gameplay.set_closed(False)
        bot.say('{0} opened game play for non operators'.format(oper))
        if channel_.gameplay.get_game_state():
            off: str = formatting.color("off", formatting.colors.RED)
            bot.say("{2}: gameplay {1} in {0}".format(channel.name, off, oper))
            channel_.gameplay.stop_game(key)

    elif set_closed:
        channel_.gameplay.set_closed(True)
        bot.say('{0} closed game play for non operators'.format(oper))
        if channel_.gameplay.get_game_state():
            off: str = formatting.color("off", formatting.colors.RED)
            bot.say("{2}: gameplay {1} in {0}".format(channel.name, off, oper))
            channel_.gameplay.stop_game(key)

    # toggle game play state
    elif toggle:
        if channel_.gameplay.get_game_state():
            channel_.gameplay.stop_game(key)
            scores = channel_.gameplay.get_scores()
            if (len(scores)):
                channel_.gameplay.show_scores(bot, scores)
            off: str = formatting.color("off", formatting.colors.RED)
            bot.say("{2}:gameplay {1} in {0}".format(channel.name, off, oper))
        else:
            channel_.gameplay.start_game()
            on: str = formatting.color("on", formatting.colors.GREEN)
            bot.say("{2}: gameplay {1} in {0}".format(channel.name, on, oper))

    # explicitly enable game play
    elif on:
        if channel_.gameplay.is_closed():
            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say('Sorry, game play requires and Op, ask an Op to open it.')
                return

        if channel_.gameplay.get_game_state():
            on: str = formatting.color("on", formatting.colors.GREEN)
            bot.say("gameplay already {1} in {0}".format(channel.name, on))
        else:
            channel_.gameplay.start_game()
            on: str = formatting.color("on", formatting.colors.GREEN)
            bot.say("{2}: gameplay {1} in {0}".format(channel.name, on, oper))

    # explicitly turn off game play
    elif off:
        if not channel_.gameplay.get_game_state():
            off: str = formatting.color("off", formatting.colors.RED)
            bot.say("gameplay already {1} in {0}".format(channel.name, off))
        else:
            off: str = formatting.color("off", formatting.colors.RED)
            bot.say("{2}: gameplay {1} in {0}".format(channel.name, off, oper))
            channel_.gameplay.stop_game(key)

    # start auto game play
    elif auto:
        if channel_.gameplay.is_closed():
            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say('Sorry, game play requires and Op, ask an Op to open it.')
                return

        bot.say('{0}: {1} game starts in {2} seconds in {3}'
                .format(oper,
                        formatting.color("auto",formatting.colors.GREEN),
                        pause,
                        channel.name,
                        pause))
        channel_.gameplay.auto_start(rounds, delay, pause)

    elif reset_scores:
        if channel_.gameplay.is_closed():
            if not channel.has_privilege(trigger.nick, plugin.OP):
                bot.say('Sorry, game play requires and Op, ask an Op to open it.')
                return
        channel_.gameplay.reset_scores()
        bot.say("{1}: player scores are reset in {0}".format(channel.name, oper))

    # you should read the instructions
    else:
        bot.say("I don't understand {0}, ignoring".format(str(trigger)))


@plugin.require_chanmsg('channel only command')
@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.command('next', 'image', 'pic')
@plugin.output_prefix('[game] ')
def on_next_image(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ fetch a random image or fetch an image based on it's id
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    image_id: int = -1
    if len(command) > 1:
        try:
            image_id: int = int(command[1])
        except:
            bot.say("{0} is not a valid number".format(command[1]))
            return
    channel = bot.channels[trigger.sender]
    oper: str = formatting.color(formatting.bold(trigger.nick), formatting.colors.BLUE)
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "next"):
        bot.say('{0} is not permitted in {1}'.format('next', channel_.get_channel_name()))
        return

    if not channel_.gameplay.get_game_state():
        off: str = formatting.color("off", formatting.colors.RED)
        bot.say("gameplay is {1} in {0}".format(channel.name, off))
    else:
        channel_.gameplay.next_image(key)
        scores = channel_.gameplay.get_scores()
        if (len(scores)):
            channel_.gameplay.show_scores(bot, scores)
        keys: list[int] = list(channel_.image_dictionary)
        num = 0
        if image_id > 0:
            if image_id not in keys:
                bot.say("I don't have an image with id: {0}".format(image_id))
                return
        else:
            if len(keys) >= 1:
                #num = random.randint(0, len(keys)-1)
                #image_id = keys[num]
                image_id = ramdom.choice(keys)
        url = channel_.image_dictionary.get_url(image_id)
        channel_.gameplay.set_game_image(image_id)
        bot.say('{2} says gimme some love [{0}]: {1}'.format(image_id, url, oper))

# morris imporve handing of loves
@plugin.require_chanmsg('channel only command')
@plugin.commands('like', 'love')
@plugin.output_prefix('[game] ')
def on_love_image(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ players interact with the currently displayed image for a period of time or until
     an operator gets the next image to display
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: str = str(trigger)
    channel = bot.channels[trigger.sender]
    nick: str = formatting.color(formatting.bold(trigger.nick), formatting.colors.MAROON)
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "love"):
        bot.say('{0} is not permitted in {1}'.format('love', channel_.get_channel_name()))
        return

    if not channel_.gameplay.get_game_state():
        off: str = formatting.color("off", formatting.colors.RED)
        bot.say("Sorry, gameplay is {1} in {0}".format(channel.name, off))
    else:
        # resplit the triggger afer we drop the command
        loves: list[str] = command.split(None, 1)
        if len(loves) > 1:
            split_loves: list[str] = channel_.gameplay.filter_loves(loves[1].split(','))
            if len(split_loves):
                channel_.gameplay.add_loves(key, str(trigger.nick), split_loves)
                bot.say("{0} loves: {1}".format(nick, split_loves[:]))
                return
        bot.say("{0} sorry no loves here '{1}'".format(str(trigger.nick), command))


@plugin.require_chanmsg('channel only command')
@plugin.commands('kiss', 'kissess')
def on_kiss(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """Slap a <target> (e.g. nickname)"""
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "kiss"):
        bot.say('{0} is not permitted in {1}'.format('kiss', channel_.get_channel_name()))
        return

    target = trigger.group(3)
    if target is None:
        target = trigger.nick
    else:
        target = formatting.plain(target)

    if not isinstance(target, sopel.tools.Identifier):
        # TODO: For Sopel 8.0+ release, switch to new bot.make_identifier() method
        # will increase reliability of below "is nick" check
        target = tools.Identifier(target)

    if not target.is_nick():
        bot.reply("You can't kiss the whole channel!")
        return

    if target not in bot.channels[trigger.sender].users:
        bot.reply("You can't kiss someone who isn't here!")
        return

    if target == bot.nick:
        if not trigger.admin:
            target = trigger.nick
        else:
            target = 'itself'

    if target in bot.config.core.admins and not trigger.admin:
        target = trigger.nick

    verb = random.choice(channel_.get_kisses())

    bot.action(verb.format(target))


@plugin.require_chanmsg('channel only command')
@plugin.command('food')
def on_food(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]
    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "food"):
        bot.say('{0} is not permitted in {1}'.format('food', channel_.get_channel_name()))
        return
    channel_.food.dispatch(bot, trigger)

@plugin.require_chanmsg('channel only command')
@plugin.command('drink')
def on_drink(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[channel_key]
    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "drink"):
        bot.say('{0} is not permitted in {1}'.format('drink', channel_.get_channel_name()))
        return
    channel_.drink.dispatch(bot, trigger)


@plugin.require_chanmsg('channel only command')
@plugin.commands('slap', 'spank')
def on_slap(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """Slap a <target> (e.g. nickname)"""
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip("#&").casefold()
    channel_ = channel_data[key]

    # test for feature enable
    if not channel_.is_command_enabled(bot, trigger, "spank"):
        bot.say('{0} is not permitted in {1}'.format('spank', channel_.get_channel_name()))
        return

    target = trigger.group(3)

    if target is None:
        target = trigger.nick
    else:
        target = formatting.plain(target)

    if not isinstance(target, sopel.tools.Identifier):
        # TODO: For Sopel 8.0+ release, switch to new bot.make_identifier() method
        # will increase reliability of below "is nick" check
        target = tools.Identifier(target)

    if not target.is_nick():
        bot.say("You can't spank the whole channel!")
        return

    if target not in bot.channels[trigger.sender].users:
        bot.reply("You can't spank someone who isn't here!")
        return

    if target == bot.nick:
        if not trigger.admin:
            target = trigger.nick
        else:
            target = 'itself'

    if target in bot.config.core.admins and not trigger.admin:
        target = trigger.nick

    verb = random.choice(channel_.get_spanks())

    bot.action(verb.format(target))


@plugin.require_chanmsg('channel only command')
@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.commands('check_urls','ck_urls', 'ck')
@plugin.output_prefix('[url] ')
def on_check_urls(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ toggle for enabling/disabling the url_checker"""
    channel = bot.channels[trigger.sender]
    channel_key: str = channel.name.strip('#&').casefold()
    if channel_data[channel_key].url_checker.is_enabled():
        channel_data[channel_key].url_checker.disable()
        channel_data[channel_key].checkpoint()
        bot.say("{0}: url checker is now disabled for {1}".format(str(trigger.nick), channel.name))
    else:
        channel_data[channel_key].url_checker.enable()
        bot.say("{0}: url checker is enabled for {1}".format(str(trigger.nick), channel.name))


@plugin.interval(2)
@plugin.output_prefix('[url_checker] ')
def check_url_callback(bot: sopel.bot.SopelWrapper):
    """ Interval callback, set at one second
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    """
    for channel_ in channel_data:
        if channel_data[channel_].url_checker.is_enabled():
            channel_data[channel_].url_checker.process_callback(bot)
            break

# morris: update help
@plugin.commands('queenb', 'qb','man','doc')
def on_help(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    global help_dict
    """ This command provides help on the command syntax and usage
    :param bot: the instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: the target that triggered the event
    :type trigger: sopel.trigger
    """
    #    "command": {
    #       "aliases": ["list of command aliases"],
    #        "priveledge": "none or operator",
    #        "usages": ["list of usages"],
    #        "examples": ["list of examples"],
    #        "short": "one line synopsis of the command",
    #        "verbose": ["The doc command is just a places holder here, to show the json struct for the help content",
    #                    "JSON has no comment facility"],
    #        "see": ["list of other command"]
    #    }

    commandLine: list[str] = trigger.split()
    if len(commandLine) == 1:
        # display the list of commands
        commands = list(help_dict)
        commands.sort()
        bot.say('Available commands:', trigger.nick)
        for key in commands:
            bot.say('{0}: {1}'.format(formatting.bold(key), help_dict[key]['short']), trigger.nick)
        bot.say('enter \'!doc command\' for help on \'command\'', trigger.nick)
    else:
        commandLine.pop(0)  # remove the !doc command verb
        while len(commandLine):
            key = commandLine[0].lower()
            if key not in help_dict:
                for ka in help_dict:
                    aliases : list[str] = help_dict[ka]['aliases']
                    if key in aliases:
                        key = ka
                        break
            if key in help_dict:
                bot.say('Command: {0}, aliases: {1}'.format(formatting.bold(key),
                                                              formatting.color(
                                                                  (' ').join(help_dict[key]['aliases']),
                                                                  formatting.colors.BLUE)), trigger.nick)
                bot.say('privelege: {0}'.format(formatting.color(help_dict[key]['privilege'],
                                                                   formatting.colors.RED)), trigger.nick)
                bot.say('usages:', trigger.nick)
                for line in help_dict[key]['usages']:
                    bot.say(formatting.color(line, formatting.colors.GREEN), trigger.nick)
                bot.say('examples:', trigger.nick)
                for line in help_dict[key]['examples']:
                    bot.say(formatting.color(line, formatting.colors.BLUE), trigger.nick)
                bot.say('Description:', trigger.nick)
                for line in help_dict[key]['verbose']:
                    bot.say(formatting.italic(line), trigger.nick)
                if 'see' in help_dict[key]:
                    bot.say('see also: {0}'.format(formatting.bold((' ').join(help_dict[key]['see']))), trigger.nick)
            else:
                found: bool = False
                #for key in keywords.keys():
                #    if keyword in key:
                #        lines: list[str] = keywords[key].splitlines()
                #        for line in lines:
                #            bot.reply(' {0}'.format(line), trigger.nick)
                #        found = True
                #        break
                if not found:
                    bot.reply('{0} doesn\'t match any commands I know'.format(commandLine[0]))
            commandLine.pop(0)


def format_rule(message:str) -> str:
    # some formatting primatives
    formats: dict[str, str] = {
        '<b>': bytes.fromhex('02').decode(encoding='utf-8', errors='ignore'),
        '<i>': bytes.fromhex('1D').decode(encoding='utf-8', errors='ignore'),
        '<u>': bytes.fromhex('1F').decode(encoding='utf-8', errors='ignore')
    }
    for key in list(formats.keys()):
        message = message.replace(key,formats[key])
    return message

@plugin.require_chanmsg('channel only command')
@plugin.commands('rules')
def on_rules(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """  Print out the rules for the channel
    """
    channel = bot.channels[trigger.sender]
    key: str = channel.name.strip('#&').casefold()
    channel_ = channel_data[key]
    channel_rules : list[str] = channel_.get_rules()
    idx = 0
    if len(channel_rules) > 0:
        bot.say(format(formatting.bold(formatting.color(f"{channel.name} Rules:", formatting.colors.RED))), trigger.nick)
        for line in channel_rules:
            idx += 1
            bot.say('{0}: {1}'.format(formatting.bold(str(idx)),
                                      formatting.italic(format_rule(line))),
                                      trigger.nick)
    else:
        bot.say('{0}: {1}'.format(formatting.bold(str(idx)),
                                  formatting.color(formatting.italic('No Rules!'),formatting.colors.GREEN)),
                                  trigger.nick)

@plugin.require_privilege(plugin.OP, "Sorry, this is an channel operator command")
@plugin.require_chanmsg('channel only command')
@plugin.command('verbose', 'vb')
@plugin.example('!verbose 1', 'sets the verbosity level in the channel')
@plugin.output_prefix('[verbose] ')
def on_verbose(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    """ cset the verbosity level for the current channel
    :param bot: instance of the sopel bot
    :type bot: sopel.bot.SopelWrapper
    :param trigger: this is the trigger for the even
    :type trigger: sopel.trigger
    """
    command: list[str] = trigger.split()
    command.pop(0)
    if len(command) > 0:
        channel = bot.channels[trigger.sender]
        chan_key: str = channel.name.strip("#&").casefold()
        channel_ = channel_data[chan_key]

        # test for feature enable
        if not channel_.is_command_enabled(bot, trigger, "verbose"):
            bot.say('{0} is not permitted in {1}'.format('verbose', channel_.get_channel_name()))
            return

        if command[0].isdigit():
            level = int(command[0])
            if level > 10:
                level = 10
            channel_.set_verbosity(level);
            bot.say('{0}: verbosity set to {1}'.format(channel.name,str(level)))
    else:
        bot.say('{0} usage: !verbose level, where level is a positive digit'.format(channel.name, trigger.nick))


@plugin.require_chanmsg('channel only command')
@plugin.command('version', 'ver')
@plugin.example('!version', 'return the version time stanp')
@plugin.output_prefix('[ver] ')
def on_version(bot: sopel.bot.SopelWrapper, trigger: sopel.trigger):
    nick  = bot.nick
    channel = bot.channels[trigger.sender]
    svi = sopel.version_info
    version = f'sopel {svi.major}.{svi.minor}.{svi.micro}.{svi.serial}'
    bot.say('{0} in {1}: {2}, categories: {3}'
            .format(bot.nick, channel.name, version, VERSION_STAMP))

# end of file