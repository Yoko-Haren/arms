"""Which discipline (learning area) a subject belongs to, read from DepEd's own curriculum.

Schools add subjects in their own words ("Gen Math", "SMAW NC I", "Komunikasyon at Pananaliksik"), and the School
Head's pages group grades by discipline, so a subject without one would sit outside every chart. classify() reads a
subject's name (then its code) against the curriculum below and names its discipline; family_for() finds that
discipline among the school's own subject families, and a subject saved without one gets it automatically
(academics/apps.py). `python manage.py classify_subjects` does the same for subjects that already exist.

The curriculum it knows:
- Junior High learning areas, K to 12 (DepEd Order No. 31, s. 2012) and MATATAG (DepEd Order No. 10, s. 2024): English,
  Filipino, Mathematics, Science, Araling Panlipunan, MAPEH (Music and Arts, PE and Health), TLE/EPP, and Edukasyon sa
  Pagpapakatao, Values Education or GMRC.
- Senior High of the 2016 curriculum: the core and applied subjects of every strand, the specialized subjects of ABM,
  HUMSS, STEM and GAS, the Sports and the Arts and Design tracks.
- The Strengthened SHS curriculum (2026): its five core subjects and the TechPro clusters.
- TVL / TechPro specializations, the TESDA qualifications (EIM NC II, SMAW NC I, Cookery NC II, CSS NC II and so on), each
  under TLE with its strand: Agri-Fishery Arts, Home Economics (Family and Consumer Science), Industrial Arts or ICT.

A strand's own department (HUMSS, ABM, Research) is used when the school has it; otherwise each such subject names the
learning area that usually keeps it (Creative Writing English, Philippine Politics and Governance Araling Panlipunan).
"""
import re
from collections import namedtuple

# code: (name, colour, icon, the ways schools name the family)
DISCIPLINES = {
    'ENG': ('English', '#6A1B9A', 'fi fi-rr-book-alt', ('ENGLISH',)),
    'FIL': ('Filipino', '#E65100', 'fi fi-rr-comment-alt', ('FILIPINO',)),
    'MATH': ('Mathematics', '#123499', 'fi fi-rr-calculator', ('MATHEMATICS', 'MATH')),
    'SCI': ('Science', '#1565C0', 'fi fi-rr-flask', ('SCIENCE',)),
    'AP': ('Araling Panlipunan', '#2D6AFF', 'fi fi-rr-globe', ('ARALING PANLIPUNAN', 'SOCIAL STUDIES')),
    'MAPEH': ('MAPEH', '#C62828', 'fi fi-rr-music-alt', ('MAPEH', 'MUSIC ARTS PHYSICAL EDUCATION AND HEALTH')),
    'TLE': ('Technology and Livelihood Education', '#4a6fd4', 'fi fi-rr-tools',
            ('TECHNOLOGY AND LIVELIHOOD EDUCATION', 'TLE', 'TVL', 'TECHPRO', 'EPP', 'TECHNICAL VOCATIONAL LIVELIHOOD')),
    'ESP': ('Edukasyon sa Pagpapakatao', '#764ba2', 'fi fi-rr-heart',
            ('EDUKASYON SA PAGPAPAKATAO', 'ESP', 'VALUES EDUCATION', 'GMRC', 'GOOD MANNERS AND RIGHT CONDUCT')),
    'HUMSS': ('Humanities and Social Sciences', '#667eea', 'fi fi-rr-users-alt', ('HUMANITIES AND SOCIAL SCIENCES', 'HUMSS')),
    'ABM': ('Accountancy, Business and Management', '#3949AB', 'fi fi-rr-briefcase',
            ('ACCOUNTANCY BUSINESS AND MANAGEMENT', 'ABM', 'BUSINESS')),
    'RES': ('Research and Inquiry', '#5E35B1', 'fi fi-rr-search', ('RESEARCH', 'RESEARCH AND INQUIRY')),
}
CORE = ('ENG', 'FIL', 'MATH', 'SCI', 'AP', 'MAPEH', 'TLE', 'ESP')

Match = namedtuple('Match', 'key fallback source strand words')

# (pattern on the cleaned name, discipline, fallback discipline or None, where the rule comes from, TVL strand or '')
# Checked in order: specific subjects before the words they contain ("Family and Consumer Science" before "Science",
# "Industrial Arts" before "Arts", "Physical Science" before "Physical Education").
_TESDA = 'a TVL / TechPro specialization (TESDA qualification)'
_SHS = 'a Senior High subject'
_JHS = 'a Junior High learning area'
_SSHS = 'a Strengthened SHS subject (2026)'
RULES = [
    # ---- TVL / TechPro specializations: Industrial Arts
    (r'\bSHIELDED METAL ARC\b|\bSMAW\b|\bGAS METAL ARC\b|\bGMAW\b|\bGAS TUNGSTEN\b|\bGTAW\b|\bWELDING\b', 'TLE', None, _TESDA, 'IA'),
    (r'\bELECTRICAL INSTALLATION\b|\bEIM\b|\bELECTRONIC PRODUCTS? ASSEMBLY\b|\bEPAS\b|\bELECTRONICS?\b', 'TLE', None, _TESDA, 'IA'),
    (r'\bAUTOMOTIVE\b|\bMOTORCYCLE\b|\bSMALL ENGINE\b|\bCARPENTRY\b|\bMASONRY\b|\bPLUMBING\b|\bTILE SETTING\b|\bPIPEFITTING\b|'
     r'\bCONSTRUCTION PAINTING\b|\bSCAFFOLDING\b|\bFURNITURE\b|\bMACHINING\b|\bREFRIGERATION\b|\bAIR CONDITIONING\b|\bRAC\b|'
     r'\bDOMRAC\b|\bMECHATRONICS\b|\bTECHNICAL DRAFTING\b|\bDRAFTING\b|\bDRIVING\b|\bPHOTOVOLTAIC\b|\bINSTRUMENTATION\b|'
     r'\bTRANSMISSION LINE\b|\bINDUSTRIAL ARTS\b', 'TLE', None, _TESDA, 'IA'),
    # ---- Home Economics, now Family and Consumer Science
    (r'\bBREAD AND PASTRY\b|\bBPP\b|\bBAKING\b|\bCOOKERY\b|\bFOOD AND BEVERAGE\b|\bFBS\b|\bHOUSEKEEPING\b|\bBEAUTY CARE\b|'
     r'\bNAIL CARE\b|\bHAIRDRESSING\b|\bBARBERING\b|\bDRESSMAKING\b|\bTAILORING\b|\bCAREGIVING\b|\bFRONT OFFICE\b|'
     r'\bTOURISM\b|\bLOCAL GUIDING\b|\bTRAVEL SERVICES\b|\bWELLNESS MASSAGE\b|\bEVENTS MANAGEMENT\b|\bHANDICRAFT\b|'
     r'\bATTRACTIONS AND THEME PARKS?\b|\bHOUSEHOLD SERVICES\b|\bHOME ECONOMICS\b|\bFAMILY AND CONSUMER SCIENCES?\b|\bFCS\b',
     'TLE', None, _TESDA, 'HE'),
    # ---- ICT
    (r'\bCOMPUTER SYSTEMS? SERVICING\b|\bCSS\b|\bCOMPUTER PROGRAMMING\b|\bPROGRAMMING\b|\bANIMATION\b|\bILLUSTRATION\b|'
     r'\bMEDICAL TRANSCRIPTION\b|\bCONTACT CENTER\b|\bBROADBAND\b|\bTELECOM\b|\bWEB DEVELOPMENT\b|\bCOMPUTER HARDWARE\b|'
     r'\bINFORMATION AND COMMUNICATIONS? TECHNOLOGY\b|\bICT\b|\bEMPOWERMENT TECHNOLOGIES\b|\bEMPOTECH\b|\bCOMPUTER\b|\bCODING\b',
     'TLE', None, _TESDA, 'ICT'),
    # ---- Agri-Fishery Arts
    (r'\bAGRICULTURAL CROPS?\b|\bAGRI ?CROPS?\b|\bANIMAL PRODUCTION\b|\bPOULTRY\b|\bSWINE\b|\bRUMINANTS?\b|\bAQUACULTURE\b|'
     r'\bFISH\w*\b|\bHORTICULTURE\b|\bLANDSCAPE\b|\bORGANIC AGRICULTURE\b|\bRICE MACHINERY\b|\bPEST MANAGEMENT\b|'
     r'\bRUBBER PRODUCTION\b|\bSLAUGHTERING\b|\bAGRICULTURE\b|\bAGRI ?FISHERY\b|\bAFA\b|\bAGRO\b', 'TLE', None, _TESDA, 'AFA'),
    (r'\bMARITIME\b|\bSEAFARING\b|\bDECK\b', 'TLE', None, _TESDA, 'MARITIME'),
    (r'\bNC ?(?:I{1,3}|IV|[1-4])\b|\bNATIONAL CERTIFICATE\b', 'TLE', None, _TESDA, ''),
    (r'\bTECHNOLOGY AND LIVELIHOOD\b|\bTLE\b|\bEPP\b|\bEDUKASYONG PANTAHANAN\b|\bTVL\b|\bTECHPRO\b|\bWORK IMMERSION\b|'
     r'\bLIVELIHOOD\b', 'TLE', None, _JHS, ''),

    # ---- Research (its own department in many schools)
    (r'\bPRACTICAL RESEARCH 1\b|\bQUALITATIVE RESEARCH\b', 'RES', 'ENG', _SHS, ''),
    (r'\bPRACTICAL RESEARCH 2\b|\bQUANTITATIVE RESEARCH\b', 'RES', 'MATH', _SHS, ''),
    (r'\bINQUIRIES\b|\bINVESTIGATIONS AND IMMERSION\b|\bRESEARCH\b|\bCAPSTONE\b|\bTHESIS\b', 'RES', 'SCI', _SHS, ''),

    # ---- ABM
    (r'\bBUSINESS MATH\w*\b', 'ABM', 'MATH', _SHS, ''),
    (r'\bAPPLIED ECONOMICS\b|\bECONOMICS\b', 'ABM', 'AP', _SHS, ''),
    (r'\bFUNDAMENTALS OF ACCOUNTANCY\b|\bFABM\b|\bACCOUNTANCY\b|\bACCOUNTING\b|\bBUSINESS FINANCE\b|\bBUSINESS ETHICS\b|'
     r'\bORGANIZATION AND MANAGEMENT\b|\bPRINCIPLES OF MARKETING\b|\bMARKETING\b|\bBUSINESS ENTERPRISE SIMULATION\b|\bBUSINESS\b',
     'ABM', 'TLE', _SHS, ''),
    (r'\bENTREPRENEURSHIP\b', 'ABM', 'TLE', _SHS, ''),

    # ---- HUMSS
    (r'\bDISCIPLINES AND IDEAS IN THE (?:APPLIED )?SOCIAL SCIENCES?\b|\bDI?ASS\b|\bDISS\b', 'HUMSS', 'AP', _SHS, ''),
    (r'\bPHILIPPINE POLITICS\b|\bPOLITICS AND GOVERNANCE\b|\bPPG\b|\bCOMMUNITY ENGAGEMENT\b|\bSOLIDARITY AND CITIZENSHIP\b|'
     r'\bTRENDS NETWORKS\b|\bCRITICAL THINKING\b|\bWORLD RELIGIONS\b|\bBELIEF SYSTEMS\b|\bPOLITICAL SCIENCE\b', 'HUMSS', 'AP', _SHS, ''),
    (r'\bCREATIVE (?:NON ?FICTION|WRITING)\b', 'HUMSS', 'ENG', _SHS, ''),
    (r'\bMALIKHAING PAGSULAT\b', 'HUMSS', 'FIL', _SHS, ''),
    (r'\bPHILOSOPHY\b', 'HUMSS', 'ESP', _SHS, ''),
    (r'\bHUMANITIES\b|\bSOCIAL SCIENCES?\b', 'HUMSS', 'AP', _SHS, ''),

    # ---- Strengthened SHS core (2026)
    (r'\bEFFECTIVE COMMUNICATION\b', 'ENG', None, _SSHS, ''),
    (r'\bMABISANG KOMUNIKASYON\b', 'FIL', None, _SSHS, ''),
    (r'\bPAG ?AARAL NG KASAYSAYAN\b|\bLIPUNANG PILIPINO\b|\bPHILIPPINE HISTORY AND SOCIETY\b', 'AP', None, _SSHS, ''),
    (r'\bLIFE AND CAREER SKILLS\b|\bLIFE SKILLS\b', 'ESP', None, _SSHS, ''),

    # ---- Science before the physical / earth / life words that PE and AP also use
    (r'\bEARTH AND LIFE SCIENCE\b|\bEARTH SCIENCE\b|\bPHYSICAL SCIENCE\b|\bDISASTER READINESS\b|\bDRRR\b|\bBIOLOGY\b|'
     r'\bCHEMISTRY\b|\bPHYSICS\b|\bGENERAL SCIENCE\b|\bENVIRONMENTAL SCIENCE\b|\bSCIENCE\b|\bSCI\b', 'SCI', None, _SHS, ''),

    # ---- MAPEH, with the Sports and the Arts and Design tracks
    (r'\bCONTEMPORARY PHILIPPINE ARTS\b|\bCREATIVE INDUSTRIES\b|\bARTS PRODUCTION\b|\bIN THE ARTS\b|\bAPPRENTICESHIP\b|'
     r'\bVISUAL ARTS?\b|\bMEDIA ARTS?\b|\bTHEATER\b|\bTHEATRE\b|\bDANCE\b', 'MAPEH', 'HUMSS', _SHS, ''),
    (r'\bSAFETY AND FIRST AID\b|\bHUMAN MOVEMENT\b|\bCOACHING\b|\bOFFICIATING\b|\bFITNESS\b|\bASPECTS OF SPORTS\b|\bSPORTS?\b',
     'MAPEH', None, _SHS, ''),
    (r'\bMAPEH\b|\bMUSIC\b|\bARTS?\b|\bPHYSICAL EDUCATION\b|\bPE AND HEALTH\b|\bPEH\b|\bHEALTH\b|\bHOPE\b|^PE\b', 'MAPEH', None, _JHS, ''),

    # ---- Values: EsP, Values Education, GMRC, Personal Development
    (r'\bEDUKASYON SA PAGPAPAKATAO\b|\bESP\b|\bVALUES\b|\bGMRC\b|\bGOOD MANNERS\b|\bPERSONAL DEVELOPMENT\b|\bPERDEV\b|'
     r'\bHOMEROOM GUIDANCE\b|\bCHRISTIAN LIVING\b|\bRELIGION\b|\bCATECHESIS\b|\bISLAMIC VALUES\b', 'ESP', None, _JHS, ''),

    # ---- Araling Panlipunan
    (r'\bARALING PANLIPUNAN\b|\bUNDERSTANDING CULTURE\b|\bUCSP\b|\bKASAYSAYAN\b|\bHISTORY\b|\bSOCIAL STUDIES\b|\bGEOGRAPHY\b|'
     r'\bEKONOMIKS\b|\bCONTEMPORARY ISSUES\b|\bAP\b', 'AP', None, _JHS, ''),

    # ---- Filipino and English
    (r'\bKOMUNIKASYON\b|\bPAGBASA AT PAGSUSURI\b|\bFILIPINO SA PILING LARANG\b|\bPILING LARANG\b|\bFILIPINO\b|\bPANITIKAN\b|'
     r'\bWIKA\b|\bFIL\b', 'FIL', None, _JHS, ''),
    (r'\bORAL COMMUNICATION\b|\bREADING AND WRITING\b|\bACADEMIC AND PROFESSIONAL PURPOSES\b|\bEAPP\b|\bLITERATURE\b|'
     r'\bMEDIA AND INFORMATION LITERACY\b|\bMIL\b|\bENGLISH\b|\bENG\b|\bJOURNALISM\b|\bSPEECH\b', 'ENG', None, _JHS, ''),

    # ---- Mathematics
    (r'\bGENERAL MATHEMATICS\b|\bSTATISTICS\b|\bPROBABILITY\b|\bPRE ?CALCULUS\b|\bCALCULUS\b|\bTRIGONOMETRY\b|\bALGEBRA\b|'
     r'\bGEOMETRY\b|\bMATH\w*\b|\bNUMERACY\b', 'MATH', None, _JHS, ''),
]
_COMPILED = [(re.compile(pattern), key, fallback, source, strand) for pattern, key, fallback, source, strand in RULES]

# when the name says nothing: the subject code's letters (MATH7, ESP10, AP8, TLE-ICT9)
_CODES = [(r'^(?:TLE|EPP|ICT|HE|IA|AFA|TVL|CSS|EIM|SMAW)', 'TLE'),          # first: EPP is TLE, not EsP
          (r'^(?:MATH|MTH|GENMATH|STAT|PRECAL|BASCAL|CAL)', 'MATH'), (r'^(?:SCI|BIO|CHEM|PHY|ELS|DRRR)', 'SCI'),
          (r'^(?:ENG|ORALCOM|EAPP|LIT|RWS|MIL)', 'ENG'), (r'^(?:FIL|KOMPAN|PAGBASA)', 'FIL'),
          (r'^(?:AP|ARPAN|UCSP|HIST)', 'AP'), (r'^(?:ESP|EP|VE|GMRC|PERDEV)', 'ESP'),
          (r'^(?:MAPEH|PE|MUS|ART|HLTH|HOPE)', 'MAPEH')]


def clean(text):
    """Upper-case words only: 'Pre-Calculus' is 'PRE CALCULUS', 'A&D' is 'A AND D'."""
    text = str(text or '').upper().replace('&', ' AND ').replace("'", '').replace('’', '')
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9 ]+', ' ', text)).strip()


def classify(name, code=''):
    """The discipline a subject belongs to, from its name, else its code: a Match (key, fallback, source, strand, words)
    or None when neither says. words is the part of the name that decided it."""
    text = clean(name)
    for pattern, key, fallback, source, strand in _COMPILED:
        found = pattern.search(text)
        if found:
            return Match(key, fallback, source, strand, found.group(0))
    letters = re.sub(r'[^A-Z]', '', str(code or '').upper())
    for pattern, key in _CODES:
        if re.match(pattern, letters):
            return Match(key, None, 'its subject code', '', str(code))
    return None


def _family_index(families):
    """{discipline key: family} for a school's families, matched by code first, then by name."""
    index = {}
    for family in families:
        code, name = clean(family.family_code), clean(family.family_name)
        for key, (title, _, _, names) in DISCIPLINES.items():
            if code == key or name == clean(title) or name in names or code in names:
                index.setdefault(key, family)
    return index


def family_for(school, name, code='', *, create=False, families=None):
    """(the school's subject family for a subject, the Match): the family of its discipline, else of the discipline that
    usually keeps it. With create, a school without either gets the discipline as a new family (DepEd's own name)."""
    from .models import SubjectFamily

    match = classify(name, code)
    if match is None:
        return None, None
    if families is None:
        families = list(SubjectFamily.objects.filter(school=school, is_active=True))
    index = _family_index(families)
    family = index.get(match.key) or (index.get(match.fallback) if match.fallback else None)
    if family is None and create:
        title, colour, icon, _ = DISCIPLINES[match.key]
        family, _ = SubjectFamily.objects.get_or_create(
            school=school, family_code=match.key,
            defaults={'family_name': title, 'color_hex': colour, 'icon_class': icon,
                      'description': 'Added by ARMS when a subject of this discipline was first added.',
                      'sort_order': max([f.sort_order for f in families] or [0]) + 1})
    return family, match


def explain(match, family):
    """One plain sentence on why a subject went to a family."""
    if match is None:
        return 'Neither its name nor its code says which discipline it is; choose one.'
    strand = {'IA': ' (Industrial Arts)', 'HE': ' (Home Economics / Family and Consumer Science)', 'ICT': ' (ICT)',
              'AFA': ' (Agri-Fishery Arts)', 'MARITIME': ' (Maritime)'}.get(match.strand, '')
    title = DISCIPLINES[match.key][0]
    where = f'"{match.words.title()}" makes it {match.source}{strand}, so {title}'
    if family is not None and clean(family.family_name) != clean(title) and family.family_code.upper() != match.key:
        where += f'; the school keeps that in {family.family_name}'
    return where + '.'
