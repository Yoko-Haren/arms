# scheduling/management/commands/seed_schedule.py

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, time, datetime, timedelta
from academics.models import SchoolYear, Quarter, Section, Subject, GradeLevel, Strand, Track, Room
from scheduling.models import ClassAssignment, ClassSchedule
from accounts.models import UserProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed schedule data for a specific teacher'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            default='User.one@deped.gov.ph',
            help='Teacher email address'
        )
        parser.add_argument(
            '--school-year',
            type=str,
            default='2025-2026',
            help='School year label'
        )

    def handle(self, *args, **options):
        email = options['email']
        school_year_label = options['school_year']
        
        self.stdout.write(f"Seeding schedule for teacher: {email}")
        
        # Get or create teacher
        teacher = self.get_or_create_teacher(email)
        if not teacher:
            self.stdout.write(self.style.ERROR(f"Could not create/find teacher: {email}"))
            return
        
        # Get or create school year
        school_year = self.get_or_create_school_year(school_year_label)
        if not school_year:
            self.stdout.write(self.style.ERROR(f"Could not create/find school year: {school_year_label}"))
            return
        
        # Get or create grade levels
        grade_levels = self.get_or_create_grade_levels()
        
        # Get or create tracks and strands
        tracks = self.get_or_create_tracks()
        strands = self.get_or_create_strands(tracks)
        
        # Get or create subjects
        subjects = self.get_or_create_subjects(grade_levels, strands)
        
        # Get or create rooms
        rooms = self.get_or_create_rooms()
        
        # Create sections
        sections = self.create_sections(school_year, grade_levels, strands)
        
        # Find Grade 11 STEM A section
        grade11_stem_section = None
        for key, section in sections.items():
            if 'Grade 11' in key and 'STEM A' in key:
                grade11_stem_section = section
                break
        
        if not grade11_stem_section:
            self.stdout.write(self.style.ERROR("Grade 11 STEM A section not found"))
            return
        
        # Create class assignments and schedules
        assignments_created = self.create_assignments_and_schedules(
            teacher, school_year, grade11_stem_section, subjects, rooms
        )
        
        self.stdout.write(self.style.SUCCESS(f"Successfully seeded schedule for {teacher.get_full_name()}"))
        self.stdout.write(self.style.SUCCESS(f"Created {assignments_created} class assignments/schedules"))

    def get_or_create_teacher(self, email):
        """Get or create teacher user."""
        try:
            teacher = User.objects.get(email=email)
            # Ensure user has teacher profile
            profile, created = UserProfile.objects.get_or_create(
                user=teacher,
                defaults={'role': 'teacher'}
            )
            if created:
                self.stdout.write(f"Created teacher profile for {email}")
            return teacher
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"Teacher {email} not found. Creating..."))
            teacher = User.objects.create_user(
                username=email,
                email=email,
                password='password123',
                first_name='User',
                last_name='One'
            )
            UserProfile.objects.create(user=teacher, role='teacher')
            self.stdout.write(f"Created teacher: {email} with password 'password123'")
            return teacher

    def get_or_create_school_year(self, label):
        """Get or create school year."""
        try:
            return SchoolYear.objects.get(year_label=label)
        except SchoolYear.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"School year {label} not found. Creating..."))
            start_year = int(label.split('-')[0])
            end_year = int(label.split('-')[1])
            sy = SchoolYear.objects.create(
                year_label=label,
                year_start=start_year,
                year_end=end_year,
                date_start=date(start_year, 7, 29),
                date_end=date(end_year, 5, 15),
                total_instructional_days=203,
                is_current=True,
                status='Active'
            )
            
            # Create quarters
            quarters_data = [
                ('Q1', 1, date(start_year, 7, 29), date(start_year, 10, 24)),
                ('Q2', 2, date(start_year, 10, 27), date(end_year, 1, 16)),
                ('Q3', 3, date(end_year, 1, 19), date(end_year, 4, 15)),
                ('Q4', 4, date(end_year, 4, 17), date(end_year, 5, 15)),
            ]
            for q_label, q_num, q_start, q_end in quarters_data:
                Quarter.objects.create(
                    school_year=sy,
                    quarter_label=q_label,
                    quarter_number=q_num,
                    date_start=q_start,
                    date_end=q_end,
                    grade_encoding_deadline=timezone.make_aware(datetime.combine(q_end, time(23, 59))),
                    grade_validation_deadline=timezone.make_aware(datetime.combine(q_end + timedelta(days=7), time(23, 59))),
                    is_current_quarter=(q_label == 'Q3')
                )
            self.stdout.write(f"Created school year {label} with quarters")
            return sy

    def get_or_create_grade_levels(self):
        """Get or create grade levels."""
        levels_data = [
            (7, 'G7', 'Grade 7', 'JHS', False),
            (8, 'G8', 'Grade 8', 'JHS', False),
            (9, 'G9', 'Grade 9', 'JHS', False),
            (10, 'G10', 'Grade 10', 'JHS', False),
            (11, 'G11', 'Grade 11', 'SHS', True),
            (12, 'G12', 'Grade 12', 'SHS', True),
        ]
        
        levels = {}
        for number, code, name, category, is_shs in levels_data:
            gl, created = GradeLevel.objects.get_or_create(
                grade_number=number,
                defaults={
                    'grade_code': code,
                    'grade_name': name,
                    'level_category': category,
                    'is_senior_high': is_shs,
                    'sort_order': number
                }
            )
            levels[number] = gl
            if created:
                self.stdout.write(f"Created grade level: {name}")
        
        return levels

    def get_or_create_tracks(self):
        """Get or create tracks."""
        tracks_data = [
            ('ACADEMIC', 'Academic Track'),
            ('TVL', 'Technical-Vocational-Livelihood'),
            ('SPORTS', 'Sports Track'),
            ('ARTS_DESIGN', 'Arts & Design Track'),
        ]
        
        tracks = {}
        for code, name in tracks_data:
            track, created = Track.objects.get_or_create(
                track_code=code,
                defaults={'track_name': name}
            )
            tracks[code] = track
            if created:
                self.stdout.write(f"Created track: {name}")
        
        return tracks

    def get_or_create_strands(self, tracks):
        """Get or create strands."""
        strands_data = [
            (tracks['ACADEMIC'], 'STEM', 'Science, Technology, Engineering and Mathematics'),
            (tracks['ACADEMIC'], 'HUMSS', 'Humanities and Social Sciences'),
            (tracks['ACADEMIC'], 'ABM', 'Accountancy, Business and Management'),
            (tracks['ACADEMIC'], 'GAS', 'General Academic Strand'),
            (tracks['TVL'], 'ICT', 'Information and Communications Technology'),
            (tracks['TVL'], 'HE', 'Home Economics'),
            (tracks['TVL'], 'IA', 'Industrial Arts'),
        ]
        
        strands = {}
        for track, code, name in strands_data:
            strand, created = Strand.objects.get_or_create(
                strand_code=code,
                defaults={
                    'track': track,
                    'strand_name': name
                }
            )
            strands[code] = strand
            if created:
                self.stdout.write(f"Created strand: {code} - {name}")
        
        return strands

    def get_or_create_subjects(self, grade_levels, strands):
        """Get or create subjects."""
        subjects = {}
        
        # JHS Core Subjects (Grades 7-10)
        jhs_subjects = [
            ('ENG', 'English', 4),
            ('MATH', 'Mathematics', 4),
            ('SCI', 'Science', 4),
            ('FIL', 'Filipino', 4),
            ('AP', 'Araling Panlipunan', 4),
            ('MAPEH', 'MAPEH', 4),
            ('TLE', 'Technology and Livelihood Education', 4),
            ('ESP', 'Edukasyon sa Pagpapakatao', 4),
        ]
        
        for grade_num in [7, 8, 9, 10]:
            gl = grade_levels[grade_num]
            for code, name, hours in jhs_subjects:
                subject_code = f"{code}{grade_num}"
                subject, created = Subject.objects.get_or_create(
                    subject_code=subject_code,
                    defaults={
                        'subject_name': f"{name} {grade_num}",
                        'subject_category': 'Core',
                        'grade_level': gl,
                        'hours_per_week': hours,
                        'is_active': True
                    }
                )
                subjects[subject_code] = subject
        
        # SHS STEM Specialized Subjects
        stem_strand = strands.get('STEM')
        if stem_strand:
            stem_subjects = [
                ('SP-STEM-PRECALC', 'Pre-Calculus', 11),
                ('SP-STEM-BASCALC', 'Basic Calculus', 11),
                ('SP-STEM-GENBIO1', 'General Biology 1', 11),
                ('SP-STEM-GENBIO2', 'General Biology 2', 12),
                ('SP-STEM-GENCHEM1', 'General Chemistry 1', 11),
                ('SP-STEM-GENCHEM2', 'General Chemistry 2', 12),
                ('SP-STEM-GENPHY1', 'General Physics 1', 11),
                ('SP-STEM-GENPHY2', 'General Physics 2', 12),
            ]
            
            for code, name, grade_num in stem_subjects:
                gl = grade_levels[grade_num]
                subject, created = Subject.objects.get_or_create(
                    subject_code=code,
                    defaults={
                        'subject_name': name,
                        'subject_category': 'Specialized',
                        'grade_level': gl,
                        'strand': stem_strand,
                        'hours_per_semester': 80,
                        'is_active': True
                    }
                )
                subjects[code] = subject
        
        # SHS Core Subjects
        shs_core_subjects = [
            ('CORE-GENMATH-G11', 'General Mathematics', 11),
            ('CORE-STATS-G11', 'Statistics and Probability', 11),
            ('CORE-PRACTICAL1-G11', 'Practical Research 1', 11),
            ('CORE-PRACTICAL2-G12', 'Practical Research 2', 12),
            ('CORE-EAPP-G11', 'English for Academic and Professional Purposes', 11),
            ('CORE-PAGBASA-G11', 'Pagbasa at Pagsusuri ng Iba\'t Ibang Teksto', 11),
            ('CORE-PEH1-G11', 'Physical Education and Health 1', 11),
            ('CORE-PEH2-G11', 'Physical Education and Health 2', 11),
            ('CORE-PHILO-G12', 'Introduction to Philosophy of the Human Person', 12),
            ('CORE-UCSP-G12', 'Understanding Culture, Society and Politics', 12),
            ('CORE-CONTEMPO-G12', 'Contemporary Philippine Arts from the Regions', 12),
            ('CORE-MIL-G12', 'Media and Information Literacy', 12),
        ]
        
        for code, name, grade_num in shs_core_subjects:
            gl = grade_levels[grade_num]
            subject, created = Subject.objects.get_or_create(
                subject_code=code,
                defaults={
                    'subject_name': name,
                    'subject_category': 'Core',
                    'grade_level': gl,
                    'hours_per_semester': 80,
                    'is_active': True
                }
            )
            subjects[code] = subject
        
        # SHS ABM Specialized Subjects
        abm_strand = strands.get('ABM')
        if abm_strand:
            abm_subjects = [
                ('SP-ABM-BUSMATH-G11', 'Business Mathematics', 11),
                ('SP-ABM-FABM1-G11', 'Fundamentals of Accountancy, Business and Management 1', 11),
                ('SP-ABM-FABM2-G12', 'Fundamentals of Accountancy, Business and Management 2', 12),
                ('SP-ABM-BUSFIN-G12', 'Business Finance', 12),
                ('SP-ABM-ORG-G11', 'Organization and Management', 11),
                ('SP-ABM-MARKETING-G12', 'Principles of Marketing', 12),
            ]
            
            for code, name, grade_num in abm_subjects:
                gl = grade_levels[grade_num]
                subject, created = Subject.objects.get_or_create(
                    subject_code=code,
                    defaults={
                        'subject_name': name,
                        'subject_category': 'Specialized',
                        'grade_level': gl,
                        'strand': abm_strand,
                        'hours_per_semester': 80,
                        'is_active': True
                    }
                )
                subjects[code] = subject
        
        self.stdout.write(f"Created/verified {len(subjects)} subjects")
        return subjects

    def get_or_create_rooms(self):
        """Get or create rooms."""
        rooms_data = [
            ('BLDG1-101', 'Room 101', 'Building 1', '1st Floor', 50),
            ('BLDG1-102', 'Room 102', 'Building 1', '1st Floor', 50),
            ('BLDG1-201', 'Room 201', 'Building 1', '2nd Floor', 45),
            ('BLDG1-202', 'Room 202', 'Building 1', '2nd Floor', 45),
            ('BLDG2-301', 'Science Lab A', 'Building 2', '3rd Floor', 40),
            ('BLDG2-302', 'Computer Lab', 'Building 2', '3rd Floor', 40),
            ('BLDG3-AV', 'AV Hall', 'Building 3', 'Ground Floor', 200),
        ]
        
        rooms = {}
        for code, name, building, floor, capacity in rooms_data:
            room, created = Room.objects.get_or_create(
                room_code=code,
                defaults={
                    'room_name': name,
                    'building': building,
                    'floor': floor,
                    'capacity': capacity,
                    'room_type': 'Classroom' if 'Room' in name else ('Science Lab' if 'Science' in name else ('Computer Lab' if 'Computer' in name else 'Auditorium')),
                    'is_active': True
                }
            )
            rooms[code] = room
        
        self.stdout.write(f"Created/verified {len(rooms)} rooms")
        return rooms

    def create_sections(self, school_year, grade_levels, strands):
        """Create sections."""
        sections = {}
        
        # JHS Sections
        jhs_sections = ['Rose', 'Lily', 'Daisy']
        for grade_num in [7, 8, 9, 10]:
            gl = grade_levels[grade_num]
            for sec_name in jhs_sections:
                section_key = f"{gl.grade_name} - {sec_name}"
                section, created = Section.objects.get_or_create(
                    section_name=sec_name,
                    grade_level=gl,
                    school_year=school_year,
                    defaults={
                        'max_capacity': 50,
                        'is_active': True,
                        'is_homeroom': True
                    }
                )
                sections[section_key] = section
        
        # SHS STEM Sections
        stem_strand = strands.get('STEM')
        if stem_strand:
            for grade_num in [11, 12]:
                gl = grade_levels[grade_num]
                for sec_name in ['STEM A', 'STEM B']:
                    section_key = f"{gl.grade_name} - {sec_name}"
                    section, created = Section.objects.get_or_create(
                        section_name=sec_name,
                        grade_level=gl,
                        school_year=school_year,
                        strand=stem_strand,
                        defaults={
                            'max_capacity': 45,
                            'is_active': True,
                            'is_homeroom': True
                        }
                    )
                    sections[section_key] = section
        
        # SHS ABM Section
        abm_strand = strands.get('ABM')
        if abm_strand:
            for grade_num in [11, 12]:
                gl = grade_levels[grade_num]
                section_key = f"{gl.grade_name} - ABM A"
                section, created = Section.objects.get_or_create(
                    section_name='ABM A',
                    grade_level=gl,
                    school_year=school_year,
                    strand=abm_strand,
                    defaults={
                        'max_capacity': 45,
                        'is_active': True,
                        'is_homeroom': True
                    }
                )
                sections[section_key] = section
        
        # SHS HUMSS Section
        humss_strand = strands.get('HUMSS')
        if humss_strand:
            for grade_num in [11, 12]:
                gl = grade_levels[grade_num]
                section_key = f"{gl.grade_name} - HUMSS A"
                section, created = Section.objects.get_or_create(
                    section_name='HUMSS A',
                    grade_level=gl,
                    school_year=school_year,
                    strand=humss_strand,
                    defaults={
                        'max_capacity': 45,
                        'is_active': True,
                        'is_homeroom': True
                    }
                )
                sections[section_key] = section
        
        self.stdout.write(f"Created/verified {len(sections)} sections")
        return sections

    def create_assignments_and_schedules(self, teacher, school_year, section, subjects, rooms):
        """Create class assignments and schedules for the teacher."""
        assignments_created = 0
        
        # Get rooms
        default_room = rooms.get('BLDG1-101')
        lab_room = rooms.get('BLDG2-301')
        computer_room = rooms.get('BLDG2-302')
        
        # Schedule data: (subject_key, day, start_time, end_time, room, is_advisory)
        schedule_data = [
            # Monday
            ('CORE-GENMATH-G11', 'Monday', '07:30', '09:00', default_room, True),
            ('SP-STEM-PRECALC', 'Monday', '09:15', '10:45', default_room, False),
            ('SP-STEM-GENPHY1', 'Monday', '11:00', '12:30', lab_room, False),
            ('CORE-PRACTICAL1-G11', 'Monday', '13:00', '14:30', default_room, False),
            
            # Tuesday
            ('CORE-STATS-G11', 'Tuesday', '07:30', '09:00', default_room, False),
            ('SP-STEM-BASCALC', 'Tuesday', '09:15', '10:45', default_room, False),
            ('SP-STEM-GENCHEM1', 'Tuesday', '11:00', '12:30', lab_room, False),
            ('CORE-EAPP-G11', 'Tuesday', '13:00', '14:30', default_room, False),
            
            # Wednesday
            ('SP-STEM-GENBIO1', 'Wednesday', '07:30', '09:00', lab_room, False),
            ('CORE-GENMATH-G11', 'Wednesday', '09:15', '10:45', default_room, False),
            ('CORE-PAGBASA-G11', 'Wednesday', '11:00', '12:30', default_room, False),
            ('SP-STEM-PRECALC', 'Wednesday', '13:00', '14:30', default_room, False),
            
            # Thursday
            ('SP-STEM-GENPHY1', 'Thursday', '07:30', '09:00', lab_room, False),
            ('CORE-PRACTICAL1-G11', 'Thursday', '09:15', '10:45', default_room, False),
            ('CORE-STATS-G11', 'Thursday', '11:00', '12:30', default_room, False),
            ('SP-STEM-BASCALC', 'Thursday', '13:00', '14:30', default_room, False),
            
            # Friday
            ('CORE-PEH1-G11', 'Friday', '07:30', '09:00', default_room, False),
            ('CORE-PEH2-G11', 'Friday', '09:15', '10:45', default_room, False),
            ('SP-STEM-GENCHEM1', 'Friday', '11:00', '12:30', lab_room, False),
            ('CORE-EAPP-G11', 'Friday', '13:00', '14:30', default_room, False),
        ]
        
        for subject_key, day, start_str, end_str, room, is_advisory in schedule_data:
            subject = subjects.get(subject_key)
            if not subject:
                self.stdout.write(self.style.WARNING(f"Subject {subject_key} not found, skipping..."))
                continue
            
            # Parse times
            start_time = time(int(start_str[:2]), int(start_str[3:]))
            end_time = time(int(end_str[:2]), int(end_str[3:]))
            
            # Create or get class assignment
            assignment, created = ClassAssignment.objects.get_or_create(
                teacher=teacher,
                section=section,
                subject=subject,
                school_year=school_year,
                semester=None,
                defaults={
                    'is_active': True,
                    'is_advisory': is_advisory,
                    'max_students': 45,
                    'minutes_per_meeting': 90,
                    'meetings_per_week': 1,
                    'default_room': room
                }
            )
            
            if created:
                assignments_created += 1
                self.stdout.write(f"  Created assignment: {subject.subject_name}")
            
            # Create or get schedule
            schedule, sched_created = ClassSchedule.objects.get_or_create(
                class_assignment=assignment,
                day_of_week=day,
                time_start=start_time,
                time_end=end_time,
                defaults={
                    'room': room,
                    'schedule_type': 'Regular',
                    'is_active': True,
                    'effective_from': date.today()
                }
            )
            
            if sched_created:
                self.stdout.write(f"    Created schedule: {day} {start_str}-{end_str}")
        
        return assignments_created