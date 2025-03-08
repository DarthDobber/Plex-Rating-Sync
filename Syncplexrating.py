from plexapi.server import PlexServer
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, POPM, ID3NoHeaderError
import os
import logging

# ============================================================
# User Settable Variables
# ============================================================

# URL of the Plex server. Replace with your actual Plex server URL.
PLEX_URL = 'http://your-plex-server:32400'

# Plex token for authentication. Replace with your actual Plex token.
PLEX_TOKEN = 'your-plex-token'

# Name of the music library in Plex. Ensure this matches the name of your library in Plex.
PLEX_MUSIC_LIBRARY_NAME = 'YourMusicLibraryName'

# Logging level for the script.
LOG_LEVEL = 'INFO'

# Test mode flag. Set to True to run in test mode without making changes, or False to apply changes.
TEST_MODE = True

# ============================================================
# Path Translation
# ============================================================

# Prefix for the music path as seen by Plex. Adjust to match your Plex server's configuration.
PLEX_PATH_PREFIX = '/Music/'

# Prefix for the music path on the local host. Adjust to match your local file system.
HOST_PATH_PREFIX = '/mnt/Music/'

# Set up logging
logging.basicConfig(level=LOG_LEVEL, format='%(message)s')
logger = logging.getLogger(__name__)

# Suppress plexapi debug output
logging.getLogger('plexapi').setLevel(logging.WARNING)

# Counters
insync = 0
justsynced = 0
notag = 0
error = 0
not_found = 0
tracks_processed = 0
total_tracks = 0

# Time tracking
start_time = time.time()

def translate_path(plex_path):
  return plex_path.replace(PLEX_PATH_PREFIX, HOST_PATH_PREFIX)

def plex_to_mp3_rating(plex_rating):
  stars = round(plex_rating / 2)
  if stars == 0:
      return 0
  elif stars == 1:
      return 1
  elif stars == 2:
      return 64
  elif stars == 3:
      return 128
  elif stars == 4:
      return 196
  else:
      return 255

def mp3_to_plex_rating(mp3_rating):
  if mp3_rating == 0:
      return 0
  elif mp3_rating == 1:
      return 2
  elif mp3_rating <= 64:
      return 4
  elif mp3_rating <= 128:
      return 6
  elif mp3_rating <= 196:
      return 8
  else:
      return 10

def get_rating(audiofile):
  try:
      popm = audiofile.tags.getall('POPM')
      for pop in popm:
          if pop.email == '':  # Check for a blank email
              return pop.rating
      return None
  except Exception as e:
      logger.error(f"Error getting rating: {str(e)}")
      return None

def set_rating(audiofile, rating):
  try:
      popm_frames = audiofile.tags.getall('POPM')
      
      # Check if a POPM frame with a blank email already exists
      popm = None
      for frame in popm_frames:
          if frame.email == '':  # Check for a blank email
              popm = frame
              break
      
      if popm is None:
          # If no existing frame, create a new one with a blank email
          popm = POPM(email='', rating=rating, count=0)
          audiofile.tags.add(popm)
      else:
          # Update the existing frame
          popm.rating = rating
      
      audiofile.save()
  except Exception as e:
      logger.error(f"Error setting rating: {str(e)}")

def process_mp3(track, host_path):
  global insync, justsynced, notag, error
  
  try:
      audiofile = MP3(host_path, ID3=ID3)
  except ID3NoHeaderError:
      logger.error(f"Error: No ID3 tag found for {track.title}")
      error += 1
      return
  except Exception as e:
      logger.error(f"Error loading MP3 file: {track.title} - {str(e)}")
      error += 1
      return

  current_rating = get_rating(audiofile)

  if isinstance(track.userRating, float):
      mp3_rating = plex_to_mp3_rating(track.userRating)
      
      if current_rating == mp3_rating:
          insync += 1
          logger.debug(f'Synchronized: {track.title} (MP3)')
      else:
          if not TEST_MODE:
              set_rating(audiofile, mp3_rating)
              
              # Verify the change
              audiofile = MP3(host_path, ID3=ID3)
              new_rating = get_rating(audiofile)
              
              if new_rating == mp3_rating:
                  justsynced += 1
                  logger.debug(f'Updated and verified: {track.title} with rating {mp3_rating}')
              else:
                  error += 1
                  logger.error(f'Failed to update: {track.title}. Expected {mp3_rating}, got {new_rating}')
          else:
              logger.debug(f'Would update: {track.title} with rating {mp3_rating}')
              justsynced += 1  # Count as synced in test mode for reporting
  else:
      if current_rating is not None:
          plex_rating = mp3_to_plex_rating(current_rating)
          if not TEST_MODE:
              track.rate(plex_rating)
          logger.debug(f'Updated Plex: {track.title} with rating {plex_rating}')
          justsynced += 1
      else:
          notag += 1

  # Final verification
  audiofile = MP3(host_path, ID3=ID3)
  final_rating = get_rating(audiofile)

def process_flac(track, host_path):
  global insync, justsynced, notag, error
  
  try:
      audiofile = FLAC(host_path)
  except Exception as e:
      logger.error(f"Error loading FLAC file: {track.title} - {str(e)}")
      error += 1
      return

  def plex_to_flac_rating(plex_rating):
      return str(min(5, max(1, round(plex_rating / 2))))

  def flac_to_plex_rating(flac_rating):
      return float(flac_rating) * 2

  if isinstance(track.userRating, float):
      plex_rating_converted = plex_to_flac_rating(track.userRating)
      
      current_rating = audiofile.get('RATING', [None])[0]
      
      if current_rating == plex_rating_converted:
          insync += 1
          logger.debug(f'Synchronized: {track.title} (FLAC)')
      else:
          if not TEST_MODE:
              audiofile['RATING'] = [plex_rating_converted]
              audiofile.save()
              
              # Verify the change
              audiofile = FLAC(host_path)
              new_rating = audiofile.get('RATING', [None])[0]
              if new_rating == plex_rating_converted:
                  justsynced += 1
                  logger.debug(f'Updated and verified local FLAC tag: {track.title} with rating {plex_rating_converted}')
              else:
                  error += 1
                  logger.error(f'Failed to update FLAC tag: {track.title}. Expected {plex_rating_converted}, got {new_rating}')
          else:
              logger.debug(f'Would update local FLAC tag: {track.title} with rating {plex_rating_converted}')
              justsynced += 1  # Count as synced in test mode for reporting
  else:
      current_rating = audiofile.get('RATING', [None])[0]
      if current_rating:
          plex_rating = flac_to_plex_rating(float(current_rating))
          if not TEST_MODE:
              track.rate(plex_rating)
          logger.debug(f'Updated Plex: {track.title} (FLAC) with rating {plex_rating}')
          justsynced += 1
      else:
          logger.debug(f'No rating found: {track.title} (FLAC)')
          notag += 1

  # Final verification
  audiofile = FLAC(host_path)
  final_rating = audiofile.get('RATING', [None])[0]

def print_progress():
    global tracks_processed, total_tracks, start_time
    
    current_time = time.time()
    elapsed_time = current_time - start_time
    
    if total_tracks > 0:
        percent_complete = (tracks_processed / total_tracks) * 100
        
        # Estimate remaining time
        if tracks_processed > 0:
            time_per_track = elapsed_time / tracks_processed
            remaining_tracks = total_tracks - tracks_processed
            estimated_remaining_time = remaining_tracks * time_per_track
            
            # Format estimated remaining time
            remaining_hours = int(estimated_remaining_time // 3600)
            remaining_minutes = int((estimated_remaining_time % 3600) // 60)
            remaining_seconds = int(estimated_remaining_time % 60)
            
            time_str = f"{remaining_hours}h {remaining_minutes}m {remaining_seconds}s"
        else:
            time_str = "calculating..."
        
        logger.info(f"Progress: {tracks_processed}/{total_tracks} tracks processed ({percent_complete:.1f}%) - ETA: {time_str}")
        logger.info(f"Current stats: {insync} in sync, {justsynced} synced, {notag} no tags, {error} errors, {not_found} not found")
    else:
        logger.info(f"Progress: {tracks_processed} tracks processed")

# Connect to Plex
logger.info("Connecting to Plex server...")
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

logger.info(f"Connected to Plex server: {plex.friendlyName}")
logger.info(f"Accessing library: {PLEX_MUSIC_LIBRARY_NAME}")

try:
    music_library = plex.library.section(PLEX_MUSIC_LIBRARY_NAME)
    albums = music_library.albums()
    
    # Count total tracks for progress tracking
    logger.info(f"Found {len(albums)} albums. Counting tracks...")
    
    # First pass to count total tracks for progress reporting
    for album in albums:
        total_tracks += len(album.tracks())
    
    logger.info(f"Starting to process {total_tracks} tracks" + (" in TEST MODE" if TEST_MODE else ""))
    
    # Now process each track
    for album_index, album in enumerate(albums):
        album_tracks = album.tracks()
        logger.info(f"Processing album {album_index+1}/{len(albums)}: '{album.title}' ({len(album_tracks)} tracks)")
        
        for track in album_tracks:
            host_path = translate_path(track.locations[0])
            
            if not os.path.exists(host_path):
                not_found += 1
                tracks_processed += 1
                continue

            if host_path.lower().endswith('.mp3'):
                process_mp3(track, host_path)
            elif host_path.lower().endswith('.flac'):
                process_flac(track, host_path)
            else:
                error += 1
            
            tracks_processed += 1
            
            # Show progress update at specified intervals
            if tracks_processed % PROGRESS_UPDATE_FREQUENCY == 0:
                print_progress()
    
except Exception as e:
    logger.error(f"Error accessing music library: {str(e)}")
    exit(1)

# Final stats Output
elapsed_time = time.time() - start_time
hours = int(elapsed_time // 3600)
minutes = int((elapsed_time % 3600) // 60)
seconds = int(elapsed_time % 60)

logger.info("\nFinal Summary:")
logger.info(f"Total processing time: {hours}h {minutes}m {seconds}s")
logger.info(f"{insync} files already in sync")
logger.info(f"{justsynced} newly synced files")
logger.info(f"{notag} files with no tags")
logger.info(f"{error} files had errors")
logger.info(f"{not_found} files not found")
logger.info(f"Total files processed: {tracks_processed}")