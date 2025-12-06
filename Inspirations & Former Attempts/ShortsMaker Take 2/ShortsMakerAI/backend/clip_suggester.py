import logging
import json
import re

# For Llama/Groq integration
try:
    from groq import Groq, APIError as GroqAPIError
    _groq_sdk_available = True
except ImportError:
    logging.warning("clip_suggester.py: groq SDK not found. Llama AI Prompt feature will be disabled.")
    _groq_sdk_available = False
    Groq, GroqAPIError = None, None # Define them as None if not available

try:
    import tiktoken
    _tiktoken_available = True
    _tiktoken_encoding = None 
except ImportError:
    logging.warning("clip_suggester.py: tiktoken library not found. Input token pre-check for Llama will be disabled.")
    _tiktoken_available = False
    tiktoken = None

# Import API keys and model configs from the main config file
from backend.config import GROQ_API_KEYS, GROQ_MODELS_CONFIG

# For sentiment analysis in suggest_clips
try:
    from backend.app_init import analyzer 
except ImportError:
    logging.warning("clip_suggester.py: Could not import analyzer from app_init. Sentiment analysis in suggestions might fail.")
    analyzer = None


logger = logging.getLogger(__name__)

# --- Llama/Groq Related Constants & Logic ---
_groq_ai_enabled = _groq_sdk_available and bool(GROQ_API_KEYS)
if not _groq_ai_enabled:
    if _groq_sdk_available and not GROQ_API_KEYS:
        logging.warning("clip_suggester.py: GROQ_API_KEYS not configured. Llama AI Prompt feature will be disabled.")
    # If SDK not available, warning already logged.

DEFAULT_MAX_OUTPUT_TOKENS_LLAMA = 200 
TOKEN_SAFETY_MARGIN = 500 
_groq_key_index = 0

def get_tiktoken_encoding_internal(encoding_name="cl100k_base"): 
    global _tiktoken_encoding # Use the module-level global
    if not _tiktoken_available: return None
    if _tiktoken_encoding is None:
        try: _tiktoken_encoding = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.error(f"Failed to get tiktoken encoding '{encoding_name}': {e}. Using 'p50k_base' as fallback.")
            try: _tiktoken_encoding = tiktoken.get_encoding("p50k_base")
            except Exception as e_fallback:
                 logger.error(f"Failed to get tiktoken fallback encoding 'p50k_base': {e_fallback}. Token counting disabled.")
                 _tiktoken_encoding = "disabled" 
    return _tiktoken_encoding if _tiktoken_encoding != "disabled" else None

def count_tokens(text, encoding_name="cl100k_base"):
    if not _tiktoken_available: return len(text) // 4 # Rough estimate
    encoding = get_tiktoken_encoding_internal(encoding_name)
    if encoding: return len(encoding.encode(text))
    return len(text) // 4 

def get_groq_client_internal(): 
    global _groq_key_index # Use the module-level global
    if not _groq_ai_enabled or not Groq or not GROQ_API_KEYS: return None, None
    selected_key = GROQ_API_KEYS[_groq_key_index]
    _groq_key_index = (_groq_key_index + 1) % len(GROQ_API_KEYS)
    try:
        client = Groq(api_key=selected_key)
        logger.info(f"Preparing Groq client with API Key index: {(_groq_key_index -1 + len(GROQ_API_KEYS)) % len(GROQ_API_KEYS)} (ends ...{selected_key[-4:]})")
        return client, selected_key
    except Exception as e:
        logger.error(f"Failed to initialize Groq client with key index {(_groq_key_index -1 + len(GROQ_API_KEYS)) % len(GROQ_API_KEYS)}: {e}")
        return None, None

def call_llama_on_groq(system_prompt, user_prompt_content, max_retries_per_key_cycle=1): 
    if not _groq_ai_enabled: 
        logger.warning("call_llama_on_groq: Groq AI is disabled or not configured.")
        return None, None
    
    num_keys = len(GROQ_API_KEYS)
    if num_keys == 0: 
        logger.error("call_llama_on_groq: No Groq API keys configured.")
        return None, None

    sorted_models = sorted(GROQ_MODELS_CONFIG, key=lambda x: x.get('priority', 99))

    for model_config in sorted_models:
        model_id = model_config.get("model_id")
        context_window = model_config.get("context_window", 8192) 
        if not model_id: continue

        if _tiktoken_available:
            estimated_input_tokens = count_tokens(system_prompt) + count_tokens(user_prompt_content)
            available_for_input = context_window - DEFAULT_MAX_OUTPUT_TOKENS_LLAMA - TOKEN_SAFETY_MARGIN
            if estimated_input_tokens > available_for_input:
                logger.warning(f"Input tokens ({estimated_input_tokens}) for model '{model_id}' (context: {context_window}) "
                               f"exceeds available space ({available_for_input}). Skipping this model.")
                continue 
        else:
            logger.warning(f"call_llama_on_groq: tiktoken not available for model '{model_id}', cannot pre-check tokens. Proceeding with API call.")

        for cycle_attempt in range(max_retries_per_key_cycle):
            key_cycle_succeeded = False 
            for key_attempt_in_cycle in range(num_keys):
                client, current_key_used = get_groq_client_internal()
                if not client:
                    logger.error(f"call_llama_on_groq: Failed to get Groq client for model '{model_id}'.")
                    continue 
                key_for_log = current_key_used[-4:] if current_key_used else 'N/A'
                try:
                    logger.info(f"Calling Groq API with model '{model_id}' key ...{key_for_log} (Key Cycle {cycle_attempt+1}, Key Attempt {key_attempt_in_cycle+1}).")
                    chat_completion = client.chat.completions.create(
                        messages=[ {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt_content}],
                        model=model_id, temperature=0.3, max_tokens=DEFAULT_MAX_OUTPUT_TOKENS_LLAMA
                    )
                    response_content = chat_completion.choices[0].message.content
                    logger.info(f"Groq API call successful: model '{model_id}' key ...{key_for_log}. Response: {response_content[:100]}...")
                    return response_content, model_id 
                except GroqAPIError as e: # Make sure GroqAPIError is defined or imported
                    logger.error(f"Groq API Error: model '{model_id}' key ...{key_for_log}: {e.status_code} - {e.message}")
                    if e.status_code == 429: # Rate limit
                        logger.warning(f"Quota/Rate limit for model '{model_id}' key ...{key_for_log}. Trying next key for this model.")
                    # For other API errors, we also try the next key in the cycle.
                except Exception as e:
                    logger.error(f"Unexpected error calling Groq API with model '{model_id}' key ...{key_for_log}: {e}", exc_info=True)
            
            if not key_cycle_succeeded and cycle_attempt < max_retries_per_key_cycle -1 :
                 logger.warning(f"All keys failed in cycle {cycle_attempt + 1} for model '{model_id}'. Retrying key cycle.")
            elif not key_cycle_succeeded: 
                 break # Break from retry cycles for this model if all keys failed in the last cycle

        logger.warning(f"Finished all API key attempts and retry cycles for model '{model_id}'. Trying next model if any.")
    
    logger.error("call_llama_on_groq: All configured models (and all their API keys/retries) failed to produce a successful response.")
    return None, None

# --- Clip Suggestion Logic ---
SUGGESTION_WEIGHTS = { 
    "user_keyword": 5.0, "high_sentiment": 3.0, "question": 2.0, "generic_keyword": 1.0, 
    "ideal_length": 1.0, "short_penalty_factor": 0.5, "long_penalty_factor": 0.8,
    "llama_relevance": 5.0 
}
IDEAL_LENGTH_MIN, IDEAL_LENGTH_MAX = 10, 45
SHORT_LENGTH_THRESHOLD, LONG_LENGTH_THRESHOLD = 5, 60
LLAMA_CHUNK_SIZE_SEGMENTS = 3 
FALLBACK_MIN_DURATION_S = 10 
FALLBACK_MAX_DURATION_S = 180 
FALLBACK_MAX_SUGGESTIONS = 3 # This constant remains, but its direct use as a hard limit in fallback was changed.

def suggest_clips(segments, user_keywords=None, ai_prompt=None, 
                  max_suggestions=10, min_duration_seconds=30, max_duration_seconds=90,
                  debug_return_all_potential=False): # New parameter
    keywords_to_check = ["important", "key", "remember", "summary", "conclusion", "finally", "amazing", "awesome", "highlight", "notice", "secret", "warning"]
    sentiment_threshold = 0.05
    user_keyword_list = [kw.strip().lower() for kw in user_keywords.split(',') if kw.strip()] if user_keywords else []
    
    if user_keyword_list: logger.info(f"suggest_clips: Using user keywords: {user_keyword_list}")
    if ai_prompt: logger.info(f"suggest_clips: Using AI Prompt: '{ai_prompt[:100]}...'")
    
    if not segments:
        logger.warning("suggest_clips: No segments provided to suggest clips from.")
        return []

    segment_scores = {seg_idx: 0.0 for seg_idx in range(len(segments))}
    segment_reasons = {seg_idx: [] for seg_idx in range(len(segments))}

    for i, segment in enumerate(segments):
        text = segment.get('text','').strip()
        lower_text = text.lower()
        if not text: continue
        
        current_score_base = 0.0
        current_reasons_base = []
        
        if "?" in text: 
            current_reasons_base.append("Q")
            current_score_base += SUGGESTION_WEIGHTS["question"]
        
        for kw in keywords_to_check:
            if kw in lower_text: 
                current_reasons_base.append(f"KW:'{kw}'")
                current_score_base += SUGGESTION_WEIGHTS["generic_keyword"]
        
        for ukw in user_keyword_list:
            if ukw in lower_text: 
                current_reasons_base.append(f"UserKW:'{ukw}'")
                current_score_base += SUGGESTION_WEIGHTS["user_keyword"]
        
        if analyzer: # Check if analyzer (nltk sentiment) is available
            vs = analyzer.polarity_scores(text)
            if abs(vs['compound']) >= sentiment_threshold: 
                current_reasons_base.append(f"Sent:{vs['compound']:.2f}")
                current_score_base += SUGGESTION_WEIGHTS["high_sentiment"] * abs(vs['compound'])
        
        segment_scores[i] += current_score_base
        segment_reasons[i].extend(current_reasons_base)

    if ai_prompt and _groq_ai_enabled and segments:
        logger.info(f"Starting Llama analysis for AI Prompt. Chunk size: {LLAMA_CHUNK_SIZE_SEGMENTS} segments.")
        for chunk_start_idx in range(0, len(segments), LLAMA_CHUNK_SIZE_SEGMENTS):
            chunk_end_idx = min(chunk_start_idx + LLAMA_CHUNK_SIZE_SEGMENTS, len(segments))
            current_chunk_segments = segments[chunk_start_idx:chunk_end_idx]
            if not current_chunk_segments: continue
            
            chunk_text = " ".join([s.get('text','').strip() for s in current_chunk_segments]).strip()
            if not chunk_text: continue
            
            chunk_start_time = current_chunk_segments[0].get('start', 0)
            chunk_end_time = current_chunk_segments[-1].get('end', 0)
            
            system_prompt_template = ("You are an expert video clip finder. Evaluate the relevance of the following transcript CHUNK "
                                      "to the user's goal. Respond ONLY with a JSON object containing a 'relevance_score' (float from 0.0 to 1.0 for the ENTIRE CHUNK) "
                                      "and a brief 'justification' (string, max 15 words for the ENTIRE CHUNK).")
            user_prompt_for_llama = (f"User's Goal: \"{ai_prompt}\"\n\nTranscript Chunk (Time: {chunk_start_time:.2f}s - {chunk_end_time:.2f}s, Segments: {chunk_start_idx}-{chunk_end_idx-1}):\n\"\"\"\n{chunk_text}\n\"\"\"\n\nJSON Response:")
            
            llama_response_str, used_model_id = call_llama_on_groq(system_prompt_template, user_prompt_for_llama)
            
            if llama_response_str and used_model_id:
                try:
                    json_match = re.search(r'\{.*?\}', llama_response_str, re.DOTALL) 
                    if json_match:
                        llama_response_json = json.loads(json_match.group(0))
                        chunk_relevance_score = float(llama_response_json.get("relevance_score", 0.0))
                        chunk_justification = llama_response_json.get("justification", "")
                        if chunk_relevance_score > 0.1:
                            logger.info(f"Chunk {chunk_start_idx}-{chunk_end_idx-1} Llama (model: {used_model_id}) relevance: {chunk_relevance_score:.2f}. Justification: {chunk_justification}")
                            for seg_idx_in_chunk in range(chunk_start_idx, chunk_end_idx):
                                segment_scores[seg_idx_in_chunk] += SUGGESTION_WEIGHTS["llama_relevance"] * chunk_relevance_score
                                segment_reasons[seg_idx_in_chunk].append(f"LLM-Chunk({used_model_id.split('/')[-1]},{chunk_relevance_score:.2f}):{chunk_justification[:25]}")
                    else: 
                        logger.warning(f"No JSON in Llama response for chunk {chunk_start_idx}-{chunk_end_idx-1} (model: {used_model_id}): {llama_response_str}")
                except (json.JSONDecodeError, ValueError, TypeError) as e_parse: 
                    logger.warning(f"Error parsing Llama JSON for chunk {chunk_start_idx}-{chunk_end_idx-1} (model: {used_model_id}, response: '{llama_response_str}'): {e_parse}")
            elif used_model_id: 
                 logger.warning(f"No Llama response for chunk {chunk_start_idx}-{chunk_end_idx-1}, prompt '{ai_prompt[:30]}...' (model attempted: {used_model_id}, or all models failed token check/API call).")

    all_potential_clips = []
    for i, segment in enumerate(segments):
        seg_dur = segment.get('end',0) - segment.get('start',0)
        current_total_score = segment_scores[i]
        current_total_reasons = list(segment_reasons[i]) # Create a copy to modify

        if IDEAL_LENGTH_MIN <= seg_dur <= IDEAL_LENGTH_MAX: 
            current_total_score += SUGGESTION_WEIGHTS["ideal_length"]
            current_total_reasons.append(f"IdealLen:{seg_dur:.1f}s")
        elif seg_dur < SHORT_LENGTH_THRESHOLD and seg_dur > 0: # Avoid penalty for zero-duration segments
            current_total_score *= SUGGESTION_WEIGHTS["short_penalty_factor"]
        elif seg_dur > LONG_LENGTH_THRESHOLD: 
            current_total_score *= SUGGESTION_WEIGHTS["long_penalty_factor"]
        
        if current_total_score > 0: 
            all_potential_clips.append({
                "id":f"sugg_{i+1}", 
                "text":segment.get('text','').strip(), 
                "start_time":segment.get('start',0), 
                "end_time":segment.get('end',0), 
                "duration":round(seg_dur,2), 
                "reason":", ".join(current_total_reasons) or "General", 
                "score":round(current_total_score,2), 
                "words":segment.get('words',[])
            })
    
    if not all_potential_clips:
        logger.info("suggest_clips: No potential clips found after scoring.")
    else:
        logger.info(f"suggest_clips: {len(all_potential_clips)} potential clips found before duration filtering.")
    
    duration_filtered_primary = [c for c in all_potential_clips if min_duration_seconds <= c['duration'] <= max_duration_seconds]
    logger.info(f"suggest_clips: {len(duration_filtered_primary)} clips after user's duration filter ({min_duration_seconds}s-{max_duration_seconds}s).")
    
    sorted_by_score_primary = sorted(duration_filtered_primary, key=lambda x: x['score'], reverse=True)
    final_suggestions, selected_ranges = [], []
    for clip in sorted_by_score_primary:
        overlap = any(max(clip['start_time'],rs) < min(clip['end_time'],re) for rs,re in selected_ranges)
        if not overlap: 
            final_suggestions.append(clip)
            selected_ranges.append((clip['start_time'], clip['end_time']))
        if len(final_suggestions) >= max_suggestions: break
    logger.info(f"suggest_clips: Selected {len(final_suggestions)} non-overlapping clips from primary filter.")

    if not final_suggestions and all_potential_clips: 
        logger.info("suggest_clips: No primary clips. Applying fallback duration filter.")
        duration_filtered_fallback = [
            c for c in all_potential_clips 
            if FALLBACK_MIN_DURATION_S <= c['duration'] <= FALLBACK_MAX_DURATION_S
        ]
        logger.info(f"suggest_clips: {len(duration_filtered_fallback)} clips with fallback duration ({FALLBACK_MIN_DURATION_S}s-{FALLBACK_MAX_DURATION_S}s).")
        
        sorted_by_score_fallback = sorted(duration_filtered_fallback, key=lambda x: x['score'], reverse=True)
        
        final_suggestions, selected_ranges = [], [] 
        for clip in sorted_by_score_fallback:
            overlap = any(max(clip['start_time'],rs) < min(clip['end_time'],re) for rs,re in selected_ranges)
            if not overlap:
                clip_copy = clip.copy() 
                clip_copy["reason"] = f"Fallback: {clip_copy.get('reason', 'General')}"
                final_suggestions.append(clip_copy)
                selected_ranges.append((clip_copy['start_time'], clip_copy['end_time']))
            # Use the main max_suggestions parameter as the limit for fallback as well
            if len(final_suggestions) >= max_suggestions: break
        logger.info(f"suggest_clips: Selected {len(final_suggestions)} non-overlapping clips from fallback (limited by max_suggestions: {max_suggestions}).")

    logger.info(f"suggest_clips: Final suggested clips count: {len(final_suggestions)}.")
    
    if debug_return_all_potential:
        # Sort all_potential_clips by score for easier review if returning them
        # This list contains all segments that got any positive score, before duration/overlap filtering.
        sorted_all_potential = sorted(all_potential_clips, key=lambda x: x['score'], reverse=True)
        logger.info(f"suggest_clips: Debug mode - returning {len(sorted_all_potential)} all potential clips along with final suggestions.")
        return final_suggestions, sorted_all_potential
    else:
        return final_suggestions
