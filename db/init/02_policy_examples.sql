INSERT INTO public.policy_examples (policy_name, resource_type, policy_expression, description)
VALUES
  (
    'patient_demographics_reception',
    'Patient',
    'role.receptionist AND clearance.demographics AND epoch.2026',
    'Reception can read patient demographics only'
  ),
  (
    'patient_nurse_basic',
    'Patient',
    '(role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026',
    'Nurse and doctors can read demographics'
  ),
  (
    'observation_lab_or_physician',
    'Observation',
    '(role.lab_technician OR role.lab_scientist OR role.doctor) AND clearance.labs AND epoch.2026',
    'Lab data for lab staff or doctors'
  ),
  (
    'condition_clinical_team',
    'Condition',
    '(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026',
    'Clinical conditions for nursing/doctor team'
  ),
  (
    'encounter_clinic_team',
    'Encounter',
    '(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026',
    'Encounter notes for clinical staff'
  ),
  (
    'medication_doctors_only',
    'MedicationRequest',
    'role.doctor AND clearance.medications AND epoch.2026',
    'Medication requests only to doctors'
  ),
  (
    'cardiology_only',
    'Observation',
    'role.doctor AND specialty.cardiology AND clearance.clinical_notes AND epoch.2026',
    'Cardiology-specific observations'
  )
ON CONFLICT (policy_name) DO NOTHING;
