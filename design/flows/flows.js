/*
 * ARMS user flows for the three school roles: Teacher, Registrar and School Head.
 * Written in Mermaid so they can be rendered here, generated in FigJam, or exported as SVG.
 * Each step names a real screen; the screens are in design/screens/ and in the Figma file.
 */
window.ARMS_FLOWS = [
  {
    id: 'role-map',
    title: 'Who does what',
    summary: 'One sign-in page sends each person to their own portal. Accounts flow downward: the School Head adds registrars, the registrar creates teachers.',
    mermaid: `flowchart LR
  signIn(["Sign in"])
  signIn --> teacher["Teacher"]
  signIn --> registrar["Registrar"]
  signIn --> head["School Head"]

  teacher --> tDash["Dashboard"]
  teacher --> tRecords["Class Records"]
  teacher --> tUpload["Upload Grades"]
  teacher --> tAssess["Assessments"]

  registrar --> rLists["Class Lists"]
  registrar --> rSections["Sections"]
  rSections --> rDetail["Section detail"]
  registrar --> rTeachers["Teachers"]
  registrar --> rGrades["Grade Validation"]
  rGrades --> rReview["Class review"]

  head --> hDash["Academic Dashboard"]
  hDash --> hSection["Section analysis"]
  head --> hPerf["School Performance"]
  head --> hUsers["User Management"]

  hUsers -. "Adds" .-> registrar
  rTeachers -. "Creates" .-> teacher

  style teacher fill:#C2E5FF,stroke:#3DADFF
  style registrar fill:#DCCCFF,stroke:#874FFF
  style head fill:#CDF4D3,stroke:#66D575`
  },
  {
    id: 'sign-in',
    title: 'Sign in and redirect by role',
    summary: 'Two ways in: password or Google. A temporary password must be replaced first, then the account is linked to Google with an emailed code. After that the system redirects to the Teacher, Registrar or School Head portal.',
    mermaid: `flowchart LR
  start(["Open ARMS"]) --> signIn["Sign-in page"]
  signIn -->|"Password"| check{"Correct?"}
  signIn -->|"Google"| google["Choose Google account"]

  check -->|"No"| wrong["Error, locked after 5 tries"]
  wrong --> signIn
  check -->|"Yes"| temp{"Temporary password?"}
  temp -->|"Yes"| setPw["Set your own password"]
  setPw --> linked
  temp -->|"No"| linked{"Google linked?"}
  linked -->|"No"| link["Link your Google account"]
  link --> code["Enter 6-digit code"]
  code --> role
  linked -->|"Yes"| role{"Role"}

  google --> known{"Linked to an account?"}
  known -->|"Yes"| role
  known -->|"Email matches"| code
  known -->|"No"| refused["Refused, use password once"]
  refused --> signIn

  role -->|"Teacher"| teacher["Teacher Dashboard"]
  role -->|"Registrar"| registrar["Registrar Dashboard"]
  role -->|"School Head"| head["Academic Dashboard"]

  style teacher fill:#C2E5FF,stroke:#3DADFF
  style registrar fill:#DCCCFF,stroke:#874FFF
  style head fill:#CDF4D3,stroke:#66D575
  style wrong fill:#FFCDC2,stroke:#FF7556
  style refused fill:#FFCDC2,stroke:#FF7556`
  },
  {
    id: 'forgot-password',
    title: 'Forgot password',
    summary: 'Three separate steps. The new-password page only opens after a correct code.',
    mermaid: `flowchart LR
  forgot["Forgot Password? link"] --> stepOne["Step 1: email or username"]
  stepOne --> mail["6-digit code emailed"]
  mail --> stepTwo["Step 2: enter the code"]
  stepTwo --> valid{"Code correct?"}
  valid -->|"Wrong, 5 tries"| stepTwo
  valid -->|"Expired, 15 min"| stepOne
  valid -->|"Yes"| stepThree["Step 3: new password"]
  stepThree --> strong{"Strong and matching?"}
  strong -->|"No"| stepThree
  strong -->|"Yes"| saved["Password saved"]
  saved --> signIn(["Sign-in page"])

  style saved fill:#CDF4D3,stroke:#66D575`
  },
  {
    id: 'teacher',
    title: 'Teacher',
    summary: 'The teacher sees their classes, uploads the E-Class Record for a quarter, checks each student\'s grades and manages quizzes.',
    mermaid: `flowchart LR
  signIn(["Sign in"]) --> dash["Teacher Dashboard"]
  dash --> records["Class Records"]
  dash --> upload["Upload Grades"]
  dash --> assess["Assessments"]
  dash --> settings["Account Settings"]

  records --> students["Students and quarter grades"]
  records --> upload
  upload --> file[/"E-Class Record file"/]
  file --> match{"Section and students match?"}
  match -->|"No"| message["Message says what to fix"]
  message --> upload
  match -->|"Yes"| draft["Grades saved as Draft"]
  draft --> records

  assess --> create["Create Assessment"]
  create --> list["Quiz listed, link to copy"]
  list --> assess

  settings --> account["Name, password, Google"]
  dash --> logout(["Logout"])

  style draft fill:#CDF4D3,stroke:#66D575
  style message fill:#FFE0C2,stroke:#FF9E42`
  },
  {
    id: 'class-list',
    title: 'Registrar: importing a class list',
    summary: 'One CSV is one class (one subject of one section). Nothing is saved until the registrar confirms the review page.',
    mermaid: `flowchart LR
  lists["Class Lists"] --> choose[/"Choose the CSV file"/]
  choose --> readable{"File can be read?"}
  readable -->|"No"| missing["Message says what is missing"]
  missing --> choose
  readable -->|"Yes"| review["Review: section, subject, students"]
  review --> account{"Instructor has an account?"}
  account -->|"Yes"| selected["Teacher pre-selected"]
  account -->|"No"| pick["Pick, create or leave unassigned"]
  selected --> confirm["Confirm and import"]
  pick --> confirm
  confirm --> enrolled["Section and subject created, students enrolled"]
  enrolled --> create{"Create account chosen?"}
  create -->|"Yes"| addTeacher["Add Teacher, name filled in"]
  addTeacher --> detail["Section detail"]
  create -->|"No"| detail

  style enrolled fill:#CDF4D3,stroke:#66D575
  style missing fill:#FFE0C2,stroke:#FF9E42`
  },
  {
    id: 'teacher-accounts',
    title: 'Registrar: teacher accounts',
    summary: 'One at a time or many from a CSV. Either way the teacher gets a temporary password and must set their own on first sign-in.',
    mermaid: `flowchart LR
  teachers["Teachers"] --> many{"How many?"}
  many -->|"One"| add["Add Teacher form"]
  many -->|"Many"| csv[/"Import from CSV"/]
  csv --> review["Review: ready and skipped rows"]
  review --> createAll["Create accounts"]
  createAll --> creds["Credentials shown once"]
  add --> temp["Temporary password shown once"]
  creds --> hand["Registrar hands over sign-in details"]
  temp --> hand
  hand --> first["Teacher signs in the first time"]
  first --> setPw["Set your own password"]
  setPw --> link["Link Google account"]
  link --> dash["Teacher Dashboard"]

  teachers --> reset["Reset password"]
  teachers --> off["Deactivate, red confirmation"]

  style dash fill:#C2E5FF,stroke:#3DADFF
  style off fill:#FFCDC2,stroke:#FF7556`
  },
  {
    id: 'section',
    title: 'Registrar: managing a section',
    summary: 'Everything about one section on one page. Teachers are listed lightest load first so the registrar can see who has time.',
    mermaid: `flowchart LR
  sections["Sections"] --> detail["Section detail"]
  detail --> students["Students"]
  detail --> classes["Classes and teachers"]
  detail --> adviser["Class adviser"]

  students --> move["Move to another section"]
  move --> moveConfirm["Confirmation dialog"]
  students --> drop["Drop"]
  drop --> dropConfirm["Red confirmation dialog"]
  dropConfirm --> dropped["Listed as Dropped, can be restored"]

  classes --> change["Change teacher"]
  change --> load["List sorted by lightest load"]
  classes --> addClass["Add a class: subject and teacher"]
  classes --> remove["Remove class, red confirmation"]

  style dropConfirm fill:#FFCDC2,stroke:#FF7556
  style remove fill:#FFCDC2,stroke:#FF7556`
  },
  {
    id: 'grades',
    title: 'A grade from upload to locked',
    summary: 'Teacher uploads, registrar validates or returns, registrar locks the period, School Head sees the results. Validated and locked grades cannot be overwritten by the teacher.',
    mermaid: `flowchart LR
  subgraph teacherLane ["Teacher"]
    upload["Upload Grades"]
    draft["Saved as Draft"]
  end
  subgraph registrarLane ["Registrar"]
    validation["Grade Validation"]
    complete{"Every student graded?"}
    incomplete["Incomplete"]
    ready["Ready to validate"]
    review["Class review"]
    decision{"Decision"}
    returned["Returned with a note"]
    validated["Validated"]
    locked["Period locked: Finalized"]
  end
  subgraph headLane ["School Head"]
    dashboard["Academic Dashboard"]
    performance["School Performance"]
  end

  upload --> draft
  draft --> validation
  validation --> complete
  complete -->|"No"| incomplete
  incomplete --> upload
  complete -->|"Yes"| ready
  ready --> review
  review --> decision
  decision -->|"Return"| returned
  returned --> upload
  decision -->|"Validate"| validated
  validated --> locked
  locked -. "Unlock to correct" .-> validated
  locked --> dashboard
  locked --> performance

  style teacherLane fill:#C2E5FF,stroke:#3DADFF
  style registrarLane fill:#DCCCFF,stroke:#874FFF
  style headLane fill:#CDF4D3,stroke:#66D575`
  },
  {
    id: 'school-head',
    title: 'School Head: monitoring and accounts',
    summary: 'The School Head reads the school\'s performance and manages only the accounts of their own school.',
    mermaid: `flowchart LR
  signIn(["Sign in"]) --> dash["Academic Dashboard"]
  dash --> mode{"View mode"}
  mode -->|"All subjects"| subject["Pick subject, year, quarter, level"]
  mode -->|"By discipline"| family["Pick a discipline"]
  subject --> results["Proficiency, KPUP profile, at-risk students"]
  family --> results
  results --> row["Click a section row"]
  row --> analysis["Section analysis and recommendation"]

  signIn --> perf["School Performance"]
  perf --> trends["Average, passing rate, attendance, trends"]

  signIn --> users["User Management"]
  users --> addReg["Add Registrar"]
  addReg --> creds["Username and temporary password shown once"]
  users --> edit["Edit user: designation dropdown"]
  users --> reset["Reset password"]
  users --> off["Deactivate, red confirmation"]

  style off fill:#FFCDC2,stroke:#FF7556`
  }
];
