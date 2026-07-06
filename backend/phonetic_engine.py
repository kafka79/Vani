import re
import unicodedata
from rapidfuzz import fuzz

class IndicPhoneticEngine:
    def __init__(self):
        # Phonetic mapping for Indic names (transliterated)
        # Maps similar sounding letters to common representative characters
        # Differentiates front vowels (E, I, Y) and back vowels (O, U) to avoid Amit vs Umit collision
        self.phonetic_map = {
            'A': 'A', 'E': 'I', 'I': 'I', 'O': 'U', 'U': 'U', 'Y': 'I',
            'B': 'B', 'V': 'B', 'W': 'B',  # V, W, B are phonetically interchanged in many Indic dialects
            'P': 'P', 'F': 'P',            # P and F map to plosive representative
            'C': 'K', 'G': 'K', 'K': 'K', 'Q': 'K',
            'D': 'T', 'T': 'T',
            'L': 'L',
            'M': 'M', 'N': 'M',
            'R': 'R',
            'S': 'S', 'Z': 'S', 'X': 'S',
            'J': 'J', 'H': '',             # H represents aspiration and is skipped in base mappings, handled in rules
        }
        
        # Indic spelling substitution rules applied before mapping
        self.indic_rules = [
            (r'CH|KSH|SH|S', 'S'),
            (r'PH|F', 'P'),
            (r'BH|B', 'B'),
            (r'DH|D|TH|T', 'T'),
            (r'GH|G|KH|K', 'K'),
            (r'JH|J', 'J'),
            (r'EE', 'I'),
            (r'OO', 'U'),
        ]

        # Alias/Synonym lookup for historical/administrative names
        self.aliases = {
            "varanasi": {"benares", "banaras", "kashi"},
            "benares": {"varanasi", "banaras", "kashi"},
            "banaras": {"varanasi", "benares", "kashi"},
            "kashi": {"varanasi", "benares", "banaras"},
            "kolkata": {"calcutta"},
            "calcutta": {"kolkata"},
            "mumbai": {"bombay"},
            "bombay": {"mumbai"},
            "chennai": {"madras"},
            "madras": {"chennai"},
            "trivandrum": {"thiruvananthapuram"},
            "thiruvananthapuram": {"trivandrum"},
            "bengaluru": {"bangalore"},
            "bangalore": {"bengaluru"},
            "kochi": {"cochin"},
            "cochin": {"kochi"},
            "puducherry": {"pondicherry"},
            "pondicherry": {"puducherry"}
        }

    def normalize(self, text):
        """Clean string: strip diacritics, convert to uppercase, replacing other characters with spaces."""
        if not text:
            return ""
        # Remove leading/trailing space and convert to uppercase
        text = text.strip().upper()
        # Strip diacritics/accents
        text = "".join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        )
        # Replace non-alphabetic/non-space characters with a space to preserve word boundaries (e.g. Sanjay-Kumar -> Sanjay Kumar)
        text = re.sub(r'[^A-Z\s]', ' ', text)
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def get_phonetic_code(self, text):
        """Generates a structured phonetic code for the given text, supporting multi-word names."""
        cleaned = self.normalize(text)
        if not cleaned:
            return ""

        words = cleaned.split()
        word_codes = []
        for word in words:
            # Apply substitution rules per word
            processed = word
            for pattern, replacement in self.indic_rules:
                processed = re.sub(pattern, replacement, processed)

            if not processed:
                continue

            first_char = processed[0]
            code = self.phonetic_map.get(first_char, first_char)
            for char in processed[1:]:
                mapped = self.phonetic_map.get(char, '')
                # Append if mapped, non-empty, and avoids contiguous duplicates
                # Prevents IndexError when code is empty (e.g. word starts with 'H' which maps to '')
                if mapped and (not code or mapped != code[-1]):
                    code += mapped
            word_codes.append(code[:6])

        return " ".join(word_codes)

    def compare(self, name1, name2, enable_aliases=True):
        """Compares two names and returns a similarity score (0-100)."""
        clean1 = name1.strip().lower()
        clean2 = name2.strip().lower()
        
        if not clean1 or not clean2:
            raise ValueError("Input names cannot be empty")
            
        # 1. Exact Match Check
        if clean1 == clean2:
            return {
                "name1": name1,
                "name2": name2,
                "code1": self.get_phonetic_code(name1),
                "code2": self.get_phonetic_code(name2),
                "score": 100.0,
                "is_similar": True,
                "match_type": "exact"
            }

        # 2. Alias Synonym Check
        if enable_aliases and clean1 in self.aliases and clean2 in self.aliases[clean1]:
            return {
                "name1": name1,
                "name2": name2,
                "code1": self.get_phonetic_code(name1),
                "code2": self.get_phonetic_code(name2),
                "score": 100.0,
                "is_similar": True,
                "match_type": "alias"
            }

        # 3. Calculate Phonetic Codes and Fuzzy String Similarity
        code1 = self.get_phonetic_code(name1)
        code2 = self.get_phonetic_code(name2)
        
        fuzzy_score = fuzz.token_sort_ratio(clean1, clean2)
        
        # 4. Hybrid Scoring Logic
        if code1 and code2 and code1 == code2:
            # Phonetic codes match. Apply a boost based on name length.
            # Shorter names have higher likelihood of collision, so we check a threshold.
            min_length = min(len(clean1), len(clean2))
            
            if min_length <= 3:
                # Require higher baseline similarity to boost short names (avoids Sun vs Sam)
                if fuzzy_score >= 40:
                    final_score = min(100, fuzzy_score + 15)
                    final_score = max(final_score, 75)
                else:
                    final_score = fuzzy_score + 10 # Little boost, no auto-match
            else:
                # Longer names with phonetic matches are highly likely to be variants
                final_score = min(100, fuzzy_score + 25)
                if fuzzy_score >= 35:
                    final_score = max(final_score, 78)
        else:
            # Phonetic mismatch. Apply a penalty to the fuzzy score.
            final_score = fuzzy_score * 0.70
            
        final_score = round(final_score, 2)
        
        return {
            "name1": name1,
            "name2": name2,
            "code1": code1,
            "code2": code2,
            "score": final_score,
            "is_similar": final_score >= 75,
            "match_type": "hybrid"
        }

# Singleton instance
engine = IndicPhoneticEngine()
