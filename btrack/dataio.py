#!/usr/bin/env python
#-------------------------------------------------------------------------------
# Name:     BayesianTracker
# Purpose:  A multi object tracking library, specifically used to reconstruct
#           tracks in crowded fields. Here we use a probabilistic network of
#           information to perform the trajectory linking. This method uses
#           positional and visual information for track linking.
#
# Authors:  Alan R. Lowe (arl) a.lowe@ucl.ac.uk
#
# License:  See LICENSE.md
#
# Created:  14/08/2014
#-------------------------------------------------------------------------------


__author__ = "Alan R. Lowe"
__email__ = "code@arlowe.co.uk"

import re
import os
import numpy as np
import time
import h5py
import csv
import json

import logging

# import core
import btypes
import constants

from collections import OrderedDict
from scipy.io import savemat



# get the logger instance
logger = logging.getLogger('worker_process')


def fate_table(tracks):
    """ Create a fate table of all of the tracks. This is used by the MATLAB
    exporter.
    """

    fate_table = {}
    for t in tracks:
        if t.fate_label not in fate_table.keys():
            fate_table[t.fate_label] = [t.ID]
        else:
            fate_table[t.fate_label].append(t.ID)

    return fate_table



def export(filename, tracks):
    """ export

    Generic exporter of track data. Infers file type from extension and writes
    appropriate file type.

    Args:
        filename: full path to output file. If no extension is specified, use
            JSON by default.
        tracks: a list of Tracklet objects to write out.

    """

    if not isinstance(filename, basestring):
        raise TypeError('Filename must be a string')

    # try to infer the file format from the extension
    _, fmt = os.path.splitext(filename)

    if not fmt:
        fmt = '.json'
        filename = filename+fmt

    if fmt not in constants.EXPORT_FORMATS:
        raise ValueError('Export format not recognised')

    if fmt == '.json':
        export_JSON(filename, tracks)
    elif fmt == '.mat':
        export_MATLAB(filename, tracks)
    elif fmt == '.hdf5':
        export_HDF(filename, tracks)
    else:
        raise Exception('How did we get here?')




def check_track_type(tracks):
    return isinstance(tracks[0], btypes.Tracklet)




def export_single_track_JSON(filename, track):
    """ export a single track as a JSON file """

    if not isinstance(filename, basestring):
        raise TypeError('Filename must be a string')

    if not isinstance(track, btypes.Tracklet):
        raise TypeError('Tracks must be of type btypes.Tracklet')

    json_export = track.to_dict()
    with open(filename, 'w') as json_file:
        json.dump(json_export, json_file, indent=2)


def export_JSON(filename, tracks):
    """ JSON Exporter for track data. """
    if not check_track_type(tracks):
        raise TypeError('Tracks must be of type btypes.Tracklet')

    # make a list of all track object data, sorted by track ID
    d = {"Tracklet_"+str(trk.ID):trk.to_dict() for trk in tracks}
    json_export = OrderedDict(sorted(d.items(), key=lambda t: t[1]['ID']))

    with open(filename, 'w') as json_file:
        json.dump(json_export, json_file, indent=2, separators=(',', ': '))


def export_all_tracks_JSON(export_dir,
                           tracks,
                           cell_type=None,
                           as_zip_archive=True):

    """ export_all_tracks_JSON

    Export all tracks as individual JSON files.

    Args:
        export_dir: the directory to export the tracks to
        tracks: a list of Track objects
        cell_type: a string representing the object (cell) type
        as_zip_archive: a boolean to enable saving to a zip archive

    Returns:
        None

    """

    assert(cell_type in ['GFP','RFP','iRFP','Phase',None])
    filenames = []

    logger.info('Writing out JSON files to dir: {}'.format(export_dir))
    for track in tracks:
        fn = "track_{}_{}.json".format(track.ID, cell_type)
        track_fn = os.path.join(export_dir, fn)
        export_single_track_JSON(track_fn, track)
        filenames.append(fn)

    # make a zip archive of the files
    if as_zip_archive:
        import zipfile
        zip_fn = "tracks_{}.zip".format(cell_type)
        full_zip_fn = os.path.join(export_dir, zip_fn)
        with zipfile.ZipFile(full_zip_fn, 'w') as zip:
            for fn in filenames:
                src_json_file = os.path.join(export_dir, fn)
                zip.write(src_json_file, arcname=fn)
                os.remove(src_json_file)

    file_stats_fn = "tracks_{}.json".format(cell_type)
    file_stats = {}
    file_stats[str(cell_type)] = {"path": export_dir,
                                  "zipped": as_zip_archive,
                                  "files": filenames}

    logger.info('Writing out JSON file list to: {}'.format(file_stats_fn))
    with open(os.path.join(export_dir, file_stats_fn), 'w') as filelist:
        json.dump(file_stats, filelist, indent=2, separators=(',', ': '))


def import_all_tracks_JSON(folder, cell_type='GFP'):
    """ import_all_tracks_JSON

    import all of the tracks as Tracklet objects, for further analysis.

    Args:
        folder: the directory where the tracks are

    Returns:
        tracks: a list of Tracklet objects
    """

    file_stats_fn = os.path.join(folder, "tracks_{}.json".format(cell_type))
    if not os.path.exists(file_stats_fn):
        raise IOError('Tracking data file not found: {}'.format(file_stats_fn))

    with open(file_stats_fn, 'r') as json_file:
        track_files = json.load(json_file)

    tracks = []
    # check to see whether this is a zipped file
    as_zipped = track_files[cell_type]['zipped']
    if as_zipped:
        import zipfile
        zip_fn = os.path.join(folder,"tracks_{}.zip".format(cell_type))
        with zipfile.ZipFile(zip_fn, 'r') as zipped_tracks:
            for track_fn in track_files[cell_type]['files']:
                track_file = zipped_tracks.read(track_fn)
                d = json.loads(track_file)
                d['cell_type'] = cell_type
                d['filename'] = track_fn
                tracks.append(btypes.Tracklet.from_dict(d))
        return tracks

    # iterate over the track files and create Track objects
    for track_fn in track_files[cell_type]['files']:
        with open(os.path.join(folder, track_fn), 'r') as track_file:
            d = json.load(track_file)
            d['cell_type'] = cell_type
            d['filename'] = track_fn
            tracks.append(btypes.Tracklet.from_dict(d))

    return tracks



def export_MATLAB(filename, tracks):
    """ MATLAB Exporter for track data. """

    if not check_track_type(tracks):
        raise TypeError('Tracks must be of type btypes.Tracklet')


    export_track = np.vstack([trk.to_array() for trk in tracks])

    output = {'tracks': export_track,
              'track_labels':['x','y','frm','ID','parentID','rootID',
                              'class_label'],
              'class_labels':['interphase','prometaphase','metaphase',
                              'anaphase','apoptosis'],
              'fate_table': fate_table(tracks)}
    savemat(filename, output)



def export_HDF(filename, tracks, dummies=[]):
    """ HDF exporter for large datasets.

    This needs to deal with two different scenarios:
        i)  The original data came from an HDF5 file, in which case the file
            should exist and tracks should be a list of references, or
        ii) The original data came from another source, and we need to create
            the entire HDF5 file structure, including the objects data

    Args:
        filename - a string representing the HDF5 file
        tracks - either a list of refs or a list of btypes.Tracklet objects

    Notes:
        None

    """

    # check to see whether we have a list of references
    if isinstance(tracks[0], list):
        # ok, we have a list of object references
        if not os.path.exists(filename):
            raise IOError('HDF5 file does not exist: {0:s}'.format(filename))

        if not isinstance(tracks[0][0], (int, long)):
            print type(tracks[0][0]), tracks[0][0]
            raise TypeError('Track references should be integers')


        h = HDF5_FileHandler(filename)
        h.write_tracks(tracks)
        if dummies:
            h.write_dummies(dummies)
        h.close()

    elif check_track_type(tracks):
        # we have a list of tracklet objects
        print 'oops!'

    else:
        raise TypeError('Tracks is of an unknown format.')



class HDF5_FileHandler_LEGACY(object):
    """ HDF5_FileHandler

    DEPRECATED: Very slow.

    Generic HDF5 file hander for reading and writing datasets. This is
    inter-operable between segmentation, tracking and analysis code.

    Basic format of the HDF file is:
        frames/
            frame_1/
                coords
                labels
                dummies
            frame_2/
            ...
    """

    def __init__(self, filename=None):
        """ Initialise the HDF file. """
        self.filename = filename

        logger.warning('HDF5_FileHandler_LEGACY has been deprecated.')
        logger.info('Opening HDF file: {0:s}'.format(filename))
        self._hdf = h5py.File(filename, 'r+') # a -file doesn't have to exist

    def __del__(self):
        self.close()

    def close(self):
        """ Close the file properly """
        if self._hdf:
            self._hdf.close()
            logger.info('Closing HDF file.')

    @property
    def objects(self):
        """ Return the objects in the file """
        # objects = [self.new_PyTrackObject(o) for o in self._hdf['objects']]
        objects = []
        ID = 0

        lambda_frm = lambda f: int(re.search('([0-9]+)', f).group(0))
        frms = sorted(self._hdf['frames'].keys(), key=lambda_frm)

        for frm in frms:
            txyz = self._hdf['frames'][frm]['coords']
            labels = None

            if 'labels' in self._hdf['frames'][frm]:
                labels = self._hdf['frames'][frm]['labels']
                assert txyz.shape[0] == labels.shape[0]

            for o in xrange(txyz.shape[0]):
                if labels is not None:
                    class_label = labels[o,:]
                else:
                    class_label = None

                # get the object type
                object_type = txyz[o,4]

                objects.append(self.new_PyTrackObject(ID, txyz[o,:], label=class_label, type=object_type))

                # increment the ID counter
                ID+=1

        return objects

    @property
    def dummies(self):
        """ Return the dummy objects in the file """
        if 'dummies' not in self._hdf: return []
        dummies = [self.new_PyTrackObject(o) for o in self._hdf['dummies']]
        return dummies

    @property
    def tracks(self):
        """ Return the tracks in the file """
        tracks = [self.new_Tracklet(t) for t in self._hdf['tracks']]
        return tracks

    def new_PyTrackObject(self, ID, txyz, label=None, type=0):
        """ Set up a new PyTrackObject quickly using data from a file """

        if label is not None:
            class_label = label[0]
        else:
            class_label = 0

        new_object = btypes.PyTrackObject()
        new_object.ID = ID
        new_object.t = txyz[0]
        new_object.x = txyz[1]
        new_object.y = txyz[2]
        new_object.z = txyz[3]
        new_object.dummy = False
        new_object.label = class_label    # DONE(arl): from the classifier
        new_object.probability = np.zeros((1,))
        new_object.type = int(type)
        return new_object


class HDF5_FileHandler(object):
    """ HDF5_FileHandler

    Generic HDF5 file hander for reading and writing datasets. This is
    inter-operable between segmentation, tracking and analysis code.

    Basic format of the HDF file is:
        frames/
            frame_1/
                coords
                labels
                dummies
            frame_2/
            ...

    Args:

    Members:

    Notes:

    """

    def __init__(self, filename=None):
        """ Initialise the HDF file. """
        self.filename = filename

        logger.info('Opening HDF file: {0:s}'.format(self.filename))
        self._hdf = h5py.File(filename, 'r') # a -file doesn't have to exist

    def __del__(self):
        self.close()

    def close(self):
        """ Close the file properly """
        if self._hdf:
            self._hdf.close()
            logger.info('Closing HDF file: {}'.format(self.filename))

    @property
    def objects(self):
        """ Return the objects in the file """
        # objects = [self.new_PyTrackObject(o) for o in self._hdf['objects']]
        objects = []
        self._ID = 0

        for ci, c in enumerate(self._hdf['objects'].keys()):
            grp = self._hdf['objects'][c]

            # read the whole dataset into memory
            # NOTE(arl): the final slice [:] reads the whole file in one go,
            # since we are unlikely to have more objects than memory and we
            # need to load them all anyway.
            txyz = grp['coords'][:]
            labels = grp['labels'][:]
            n_obj = txyz.shape[0]
            logger.info('Loading {} {}...'.format(c, txyz.shape))
            obj = [self.new_PyTrackObject(txyz[i,:], label=labels[i,:], obj_type=ci+1) for i in range(n_obj)]
            objects += obj
        return objects

    @property
    def dummies(self):
        """ Return the dummy objects in the file """
        pass

    @property
    def tracks(self):
        """ Return the tracks in the file """
        pass

    def new_PyTrackObject(self, txyz, label=None, obj_type=0):
        """ Set up a new PyTrackObject quickly using data from a file """

        if label is not None:
            class_label = label[0]
        else:
            class_label = 0

        new_object = btypes.PyTrackObject()
        new_object.ID = self._ID
        new_object.t = txyz[0].astype('int')
        new_object.x = txyz[1]
        new_object.y = txyz[2]
        new_object.z = txyz[3]
        new_object.dummy = False
        new_object.label = class_label    # DONE(arl): from the classifier
        new_object.probability = np.zeros((1,))
        new_object.type = int(obj_type)

        self._ID += 1
        return new_object