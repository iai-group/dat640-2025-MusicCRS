#!/usr/bin/env python3
"""
Test script for QA system question patterns.
Tests all supported question types with various formulations.
"""

from musiccrs.qa_system import QASystem


def test_qa_questions():
    """Test various question formats supported by the QA system."""
    qa = QASystem()
    
    # Test categories
    test_cases = {
        "Track Album Questions": [
            "what album is hey jude by the beatles on",
            "what album does hey jude by the beatles appear on",
            "which album is bohemian rhapsody by queen on",
            "what album does city of blinding lights by U2 appear on?",
            "which album is hey jude from the beatles from",
            "what album is 'Stairway to Heaven' by Led Zeppelin on",
        ],
        
        "Track Artist Questions": [
            "who sings hey jude",
            "who performs bohemian rhapsody",
            "who recorded city of blinding lights",
            "who made blinding lights",
            "who is the artist of hey jude",
            "who was the artist for bohemian rhapsody",
        ],
        
        "Track Exists Questions": [
            "do you have hey jude by the beatles",
            "do you have the song bohemian rhapsody by queen",
            "is hey jude by the beatles in the database",
            "is city of blinding lights by U2 in your library",
        ],
        
        "Track Info Questions": [
            "tell me about hey jude by the beatles",
            "tell me about the song bohemian rhapsody by queen",
            "what info about city of blinding lights by U2",
            "give me information on hey jude by the beatles",
        ],
        
        "Artist Track Count Questions": [
            "how many songs by the beatles",
            "how many tracks from queen",
            "how many songs does U2 have",
            "how many tracks are there by led zeppelin",
            "how many songs do the beatles have",
        ],
        
        "Artist Albums Questions": [
            "what albums does the beatles have",
            "what albums did queen release",
            "what albums has U2 made",
            "list albums by the beatles",
            "show albums from queen",
            "tell me the albums by led zeppelin",
        ],
        
        "Artist Top Tracks Questions": [
            "what are the top songs by the beatles",
            "what are the most popular tracks by queen",
            "what are the best songs from U2",
            "show me top tracks by led zeppelin",
            "show me the most popular songs by the beatles",
        ],
        
        "Similar Artists Questions": [
            "what artists are like the beatles",
            "which artists are similar to queen",
            "who are artists similar to U2",
            "who sounds like the beatles",
            "find artists like queen",
            "find me similar to led zeppelin",
        ],
    }
    
    print("=" * 80)
    print("QA SYSTEM TEST QUESTIONS")
    print("=" * 80)
    print()
    
    total_tests = 0
    matched_tests = 0
    disambiguation_tests = 0
    
    for category, questions in test_cases.items():
        print(f"\n{'=' * 80}")
        print(f"{category}")
        print(f"{'=' * 80}\n")
        
        for question in questions:
            total_tests += 1
            result = qa.answer_question(question)
            
            status = "❌ NO MATCH"
            detail = ""
            
            if isinstance(result, dict):
                matched_tests += 1
                disambiguation_tests += 1
                status = "🔀 DISAMBIGUATION"
                num_options = len(result.get('options', []))
                detail = f" ({num_options} options)"
                if result.get('options'):
                    first_opt = result['options'][0]
                    detail += f"\n     → {first_opt[1]} - {first_opt[2]}"
                    if first_opt[3]:
                        detail += f" (album: {first_opt[3]})"
            elif isinstance(result, str):
                matched_tests += 1
                status = "✅ DIRECT ANSWER"
                # Extract key info from HTML response
                if "is on the album" in result:
                    import re
                    album_match = re.search(r'is on the album <b>([^<]+)</b>', result)
                    if album_match:
                        detail = f"\n     → Album: {album_match.group(1)}"
                elif "has <b>" in result and "tracks" in result:
                    count_match = re.search(r'has <b>(\d+)</b> tracks', result)
                    if count_match:
                        detail = f"\n     → {count_match.group(1)} tracks"
                else:
                    # Show first 60 chars
                    clean = result.replace('<b>', '').replace('</b>', '').replace('<br/>', ' ')
                    detail = f"\n     → {clean[:60]}..."
            
            print(f"Q: {question}")
            print(f"   {status}{detail}")
            print()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total questions tested: {total_tests}")
    print(f"Successfully matched: {matched_tests} ({matched_tests/total_tests*100:.1f}%)")
    print(f"  - Direct answers: {matched_tests - disambiguation_tests}")
    print(f"  - Disambiguation: {disambiguation_tests}")
    print(f"No match: {total_tests - matched_tests}")
    print()
    
    if matched_tests == total_tests:
        print("✅ ALL TESTS PASSED!")
    else:
        print("⚠️  Some questions not recognized")
    print()


def test_specific_user_questions():
    """Test the specific questions from user interaction."""
    qa = QASystem()
    
    print("\n" + "=" * 80)
    print("USER-REPORTED QUESTIONS")
    print("=" * 80)
    print()
    
    user_questions = [
        "what album does city of blinding lights by U2 appear on?",
        "what album is hey jude by the beatles on",
        "who sings bohemian rhapsody",
        "how many songs by the beatles",
    ]
    
    for question in user_questions:
        result = qa.answer_question(question)
        
        print(f"Q: {question}")
        
        if isinstance(result, dict):
            print(f"   🔀 Disambiguation needed: {len(result.get('options', []))} options")
            for i, opt in enumerate(result.get('options', [])[:3], 1):
                print(f"      {i}. {opt[1]} - {opt[2]}", end="")
                if opt[3]:
                    print(f" (album: {opt[3]})", end="")
                print()
        elif isinstance(result, str):
            # Clean HTML for display
            import re
            clean = result.replace('<b>', '').replace('</b>', '').replace('<br/>', '\n     ')
            clean = re.sub(r'<[^>]+>', '', clean)  # Remove remaining HTML tags
            print(f"   ✅ {clean}")
        else:
            print(f"   ❌ Not recognized")
        
        print()


if __name__ == "__main__":
    import sys
    
    # Check if database exists
    from pathlib import Path
    db_path = Path("data/mpd.sqlite")
    if not db_path.exists():
        print("❌ Database not found at data/mpd.sqlite")
        print("   Please run: python tools/build_mpd_sqlite.py")
        sys.exit(1)
    
    try:
        test_qa_questions()
        test_specific_user_questions()
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
