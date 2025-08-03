"""
Script to search a user's Flickr photostream for images taken with a specific
camera and add them to a photoset (album).

This script demonstrates how to authenticate with the Flickr API using the
``flickrapi`` library, search for photos belonging to a particular user,
filter those photos by camera model using EXIF data, and then either create a
new album or add the matching photos to an existing one.  The target user
and camera model are configurable, so you can adapt the script for your own
account and camera.

Before running this script you must obtain an API key and secret from the
Flickr App Garden.  Visit ``https://www.flickr.com/services/api/keys/`` and
click **Create an App**.  Choose a name, description and callback URL (for
command‑line scripts you can supply ``http://localhost``) and make sure to
request ``write`` permissions.  Once the application is created, Flickr
displays your API key and secret.  These values should be stored in the
``API_KEY`` and ``API_SECRET`` variables below, or loaded from environment
variables or a configuration file.

When you run this script for the first time it will open a browser window
asking you to log in to Flickr and authorise the application.  After
authorisation the script stores an access token on disk so that future runs
won't need to re‑authenticate.  The authentication flow is handled by the
``authenticate_via_browser`` method of the ``FlickrAPI`` class【141522280467382†L50-L60】.

Dependencies:
  * flickrapi (install with ``pip install flickrapi``)
  * requests (part of the Python standard library since Python 3.11, but
    included here if you prefer to use requests directly)

Usage example::

    python add_flickr_photos_to_album.py \
        --user-id 87729121@N00 \
        --camera-model "Canon EOS 7D Mark II" \
        --album-title "Canon 7D Mark II shots"

By default the script creates a new album using the first matching photo as
its primary image.  To append photos to an existing album instead, pass the
``--photoset-id`` argument with the numeric album identifier.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional

import flickrapi


# ===========================================================================
# Configuration
# Replace these strings with your own API credentials.  You can also supply
# them on the command line via --api-key and --api-secret, or set the
# FLICKR_API_KEY and FLICKR_API_SECRET environment variables in your shell.
API_KEY: str = ""
API_SECRET: str = ""


def authenticate(api_key: str, api_secret: str, perms: str = "write") -> flickrapi.FlickrAPI:
    """Authenticate with Flickr and return an authorised FlickrAPI instance.

    The ``flickrapi`` library encapsulates the OAuth 1.0a flow used by Flickr.
    Calling ``authenticate_via_browser`` will open a browser window for
    authorisation and store the resulting token on disk【141522280467382†L50-L60】.  If a
    valid token exists from a previous session then no browser will be opened.

    Parameters
    ----------
    api_key : str
        Your Flickr API key.
    api_secret : str
        Your Flickr API secret.
    perms : str
        Permission level required for API calls.  Must be one of "read",
        "write" or "delete".  Creating albums and adding photos requires
        ``write`` permission【801413100068362†L40-L55】.

    Returns
    -------
    flickrapi.FlickrAPI
        An authenticated Flickr API object.
    """
    flickr = flickrapi.FlickrAPI(api_key, api_secret, format='parsed-json')
    # Try to authenticate via stored token; if it fails, open the browser.
    if not flickr.token_valid(perms=perms):
        # Get a request token and authorise the application in the user's browser.
        flickr.authenticate_via_browser(perms=perms)
    return flickr


def search_photos_by_user(flickr: flickrapi.FlickrAPI, user_id: str, extras: str = "machine_tags", per_page: int = 500) -> List[Dict[str, str]]:
    """Retrieve all public photos for a given user.

    Flickr limits searches to a maximum of 4,000 results.  The `per_page`
    argument controls the number of results returned per API call (maximum
    500).  This function iterates through pages until all results are
    collected.

    We request the ``machine_tags`` extra so that each photo's machine tags
    are returned in the search response【688176185541402†L301-L307】.  Machine tags are
    structured, colon‑separated tags that Flickr generates from EXIF data
    (for example ``camera:model=e-m1markii`` or ``exif:model=Canon EOS 7D Mark II``).

    Parameters
    ----------
    flickr : flickrapi.FlickrAPI
        Authenticated Flickr API instance.
    user_id : str
        Flickr NSID of the user whose photos should be searched.  A value of
        ``me`` can be used to search the authenticated user's photos【688176185541402†L54-L56】.
    extras : str
        Comma‑separated list of extra fields to return.  Default is
        ``machine_tags``【688176185541402†L301-L307】.
    per_page : int
        Number of results per page; maximum 500.

    Returns
    -------
    List[Dict[str, str]]
        A list of dictionaries representing photo metadata returned by
        ``flickr.photos.search``.
    """
    photos: List[Dict[str, str]] = []
    page = 1
    while True:
        response = flickr.photos.search(user_id=user_id, extras=extras, per_page=per_page, page=page)
        photos_page = response['photos']['photo']
        photos.extend(photos_page)
        # Pagination: if we've reached the last page, break.
        if page >= int(response['photos']['pages']):
            break
        page += 1
        # Respect Flickr's rate limits by sleeping briefly between requests
        time.sleep(1)
    return photos


def get_camera_for_photo(flickr: flickrapi.FlickrAPI, photo_id: str) -> Optional[str]:
    """Return the camera model for a given photo using EXIF data.

    This function calls ``flickr.photos.getExif`` and scans the returned EXIF
    tags for a label or tag equal to "Model".  When a Model tag is found,
    its ``raw`` value is returned.  If the photo's owner has disabled EXIF
    sharing, or no Model tag is present, the function returns ``None``.

    Parameters
    ----------
    flickr : flickrapi.FlickrAPI
        Authenticated Flickr API instance.
    photo_id : str
        ID of the photo to inspect.

    Returns
    -------
    Optional[str]
        The camera model string (for example "Canon EOS 7D Mark II"), or
        ``None`` if not found.
    """
    try:
        exif = flickr.photos.getExif(photo_id=photo_id)
    except flickrapi.exceptions.FlickrError:
        # The photo may not have publicly available EXIF data.
        return None
    tags = exif.get('photo', {}).get('exif', [])
    for tag in tags:
        # The 'tag' key holds the numeric tag code, 'label' holds the human
        # friendly name.  We check both to be thorough.
        if tag.get('label', '').lower() == 'model' or tag.get('tag', '').lower() == 'model':
            raw = tag.get('raw')
            if isinstance(raw, dict):
                return raw.get('_content')
            else:
                return raw
    return None


def filter_photos_by_camera(flickr: flickrapi.FlickrAPI, photos: List[Dict[str, str]], camera_model: str) -> List[str]:
    """Filter a list of photos by camera model.

    Parameters
    ----------
    flickr : flickrapi.FlickrAPI
        Authenticated Flickr API instance.
    photos : List[Dict[str, str]]
        Photo metadata objects as returned by ``search_photos_by_user``.
    camera_model : str
        The camera model to match, e.g. "Canon EOS 7D Mark II".  Matching is
        case‑insensitive.

    Returns
    -------
    List[str]
        A list of photo IDs that match the requested camera model.
    """
    matching_ids: List[str] = []
    for photo in photos:
        photo_id = photo['id']
        # Attempt to determine the camera model from machine tags first.  Many
        # photos include structured tags like "camera:model=eos_7d_mark_ii" or
        # "exif:model=Canon EOS 7D Mark II" in their machine_tags field.  This
        # avoids extra API calls when available.
        machine_tags = photo.get('machine_tags', '') or ''
        if machine_tags:
            lower_tags = machine_tags.lower()
            if camera_model.lower().replace(' ', '').replace('-', '').replace('_', '') in lower_tags.replace(' ', '').replace('-', '').replace('_', ''):
                matching_ids.append(photo_id)
                continue
        # Fallback to EXIF data if machine tags aren't present or don't match.
        model = get_camera_for_photo(flickr, photo_id)
        if model and model.lower() == camera_model.lower():
            matching_ids.append(photo_id)
    return matching_ids


def create_photoset(flickr: flickrapi.FlickrAPI, title: str, primary_photo_id: str, description: str = "") -> str:
    """Create a new photoset and return its ID.

    Flickr requires a primary photo when creating a new set【952325859399986†L46-L56】.  The primary
    photo becomes the album cover and must belong to the calling user.

    Parameters
    ----------
    flickr : flickrapi.FlickrAPI
        Authenticated Flickr API instance.
    title : str
        Title for the new photoset.
    primary_photo_id : str
        ID of the photo that will serve as the primary image【952325859399986†L46-L56】.
    description : str
        Optional description of the photoset.

    Returns
    -------
    str
        The newly created photoset's ID.
    """
    resp = flickr.photosets.create(title=title, primary_photo_id=primary_photo_id, description=description)
    return resp['photoset']['id']


def add_photos_to_photoset(flickr: flickrapi.FlickrAPI, photoset_id: str, photo_ids: List[str]) -> None:
    """Add a list of photos to an existing photoset.

    Each photo is added individually using ``flickr.photosets.addPhoto``【801413100068362†L40-L55】.
    Note that this method returns an empty response upon success【801413100068362†L59-L60】.

    Parameters
    ----------
    flickr : flickrapi.FlickrAPI
        Authenticated Flickr API instance.
    photoset_id : str
        ID of the photoset to update【801413100068362†L52-L55】.
    photo_ids : List[str]
        List of photo IDs to add to the set.  Photos already in the set will
        trigger a "photo already in set" error【801413100068362†L70-L71】, so duplicates
        should be avoided.
    """
    for pid in photo_ids:
        flickr.photosets.addPhoto(photoset_id=photoset_id, photo_id=pid)
        # Flickr enforces rate limits; include a short delay between calls.
        time.sleep(0.5)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command‑line arguments."""
    parser = argparse.ArgumentParser(description="Search for photos by camera and add them to a Flickr album.")
    parser.add_argument('--api-key', type=str, default=API_KEY, help='Flickr API key (override default)')
    parser.add_argument('--api-secret', type=str, default=API_SECRET, help='Flickr API secret (override default)')
    parser.add_argument('--user-id', type=str, required=True, help='Flickr NSID of the user whose photos to search')
    parser.add_argument('--camera-model', type=str, required=True, help='Camera model string to match (e.g. "Canon EOS 7D Mark II")')
    parser.add_argument('--photoset-id', type=str, default=None, help='Existing photoset ID to add photos to.  If omitted, a new set will be created.')
    parser.add_argument('--album-title', type=str, default='Camera photos', help='Title for the new photoset (only used when creating a new set)')
    parser.add_argument('--album-desc', type=str, default='', help='Description for the new photoset (optional)')
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    api_key = args.api_key
    api_secret = args.api_secret
    if not api_key or not api_secret:
        print("Error: You must specify an API key and secret. See the script header for instructions.")
        sys.exit(1)

    flickr = authenticate(api_key, api_secret, perms='write')

    # Retrieve all photos for the user with machine tags included.
    print(f"Searching for photos belonging to user {args.user_id}…")
    photos = search_photos_by_user(flickr, user_id=args.user_id)
    print(f"Retrieved {len(photos)} photos. Filtering by camera model…")

    # Filter the photos by the desired camera model.
    matching_ids = filter_photos_by_camera(flickr, photos, args.camera_model)
    if not matching_ids:
        print(f"No photos found for camera model '{args.camera_model}'. Exiting.")
        return
    print(f"Found {len(matching_ids)} photo(s) taken with {args.camera_model}.")

    # Determine whether to create a new photoset or use an existing one.
    if args.photoset_id:
        photoset_id = args.photoset_id
        print(f"Adding photos to existing photoset {photoset_id}…")
        add_photos_to_photoset(flickr, photoset_id, matching_ids)
        print("Done.")
    else:
        # Use the first photo as the primary image for the new album and add
        # the remainder afterwards.
        primary_id = matching_ids[0]
        rest_ids = matching_ids[1:]
        print(f"Creating new photoset '{args.album_title}'…")
        photoset_id = create_photoset(flickr, title=args.album_title, primary_photo_id=primary_id, description=args.album_desc)
        print(f"Created photoset {photoset_id}. Adding remaining photos…")
        if rest_ids:
            add_photos_to_photoset(flickr, photoset_id, rest_ids)
        print("All photos added.")


if __name__ == '__main__':
    main()