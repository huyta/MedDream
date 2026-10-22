using System.Globalization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using RisApi.Data;
using RisApi.Models;

namespace RisApi.Controllers;

/// <summary>
/// DICOM Modality Worklist (MWL) Controller.
/// Serves live scheduled examination datasets to Orthanc PACS or modality SCUs
/// formatted with explicit DICOM Hexadecimal Tag keys matching DICOM PS 3.4 Annex K.
/// </summary>
[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class WorklistController : ControllerBase
{
    private readonly RisDbContext _dbContext;
    private readonly ILogger<WorklistController> _logger;

    public WorklistController(RisDbContext dbContext, ILogger<WorklistController> logger)
    {
        _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>
    /// Fetches scheduled exams filtered by modality and scheduled date.
    /// Returns a JSON array formatted with explicit DICOM hexadecimal tag keys.
    /// </summary>
    /// <param name="modality">Optional modality code filter (e.g., CT, MR, US, DX, CR).</param>
    /// <param name="date">Optional date filter in DICOM DA format (YYYYMMDD). Defaults to today's date if omitted.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>HTTP 200 with an array of DICOM-tagged worklist items.</returns>
    [HttpGet]
    public async Task<IActionResult> GetWorklist(
        [FromQuery] string? modality = null,
        [FromQuery] string? date = null,
        CancellationToken cancellationToken = default)
    {
        _logger.LogInformation("Incoming MWL query: Modality='{Modality}', Date='{Date}'", modality, date);

        // 1. Resolve Target Scheduled Date (DICOM DA Format: YYYYMMDD)
        DateTime targetDate;
        if (!string.IsNullOrWhiteSpace(date))
        {
            // DICOM standard date format YYYYMMDD (or handle date ranges like YYYYMMDD-YYYYMMDD)
            var cleanDate = date.Trim();
            if (cleanDate.Contains('-'))
            {
                cleanDate = cleanDate.Split('-')[0].Trim();
            }

            if (!DateTime.TryParseExact(cleanDate, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out targetDate))
            {
                _logger.LogWarning("Invalid date parameter received: '{Date}'. Expected YYYYMMDD.", date);
                return BadRequest(new { error = $"Invalid date format '{date}'. Expected YYYYMMDD." });
            }
        }
        else
        {
            // Default to today (UTC)
            targetDate = DateTime.UtcNow.Date;
        }

        // Establish range boundaries for SARGable indexing on PostgreSQL
        var startOfDay = DateTime.SpecifyKind(targetDate.Date, DateTimeKind.Utc);
        var endOfDay = startOfDay.AddDays(1);

        try
        {
            // 2. Query Scheduled Exams from PostgreSQL via EF Core
            var query = _dbContext.Exams
                .AsNoTracking()
                .Include(e => e.Patient)
                .Where(e => e.ScheduledDateTime >= startOfDay && e.ScheduledDateTime < endOfDay)
                .Where(e => e.Status == ExamStatus.Scheduled || e.Status == ExamStatus.Waiting);

            // Apply optional Modality filter (case-insensitive)
            if (!string.IsNullOrWhiteSpace(modality))
            {
                var cleanModality = modality.Trim().ToUpperInvariant();
                query = query.Where(e => e.Modality.ToUpper() == cleanModality);
            }

            var exams = await query
                .OrderBy(e => e.ScheduledDateTime)
                .ToListAsync(cancellationToken);

            _logger.LogInformation("Found {Count} scheduled exam(s) matching criteria.", exams.Count);

            // 3. Map to Explicit DICOM Hexadecimal Tag Dictionaries
            var worklistResponses = exams.Select(MapToDicomDataset).ToList();

            return Ok(worklistResponses);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to retrieve modality worklist entries from database.");
            return StatusCode(500, new { error = "An internal server error occurred while retrieving worklist items." });
        }
    }

    /// <summary>
    /// Generates randomized Modality Worklist (MWL) test examples for development, simulation, and testing.
    /// Creates realistic patient demographics and scheduled imaging exams for today in PostgreSQL.
    /// </summary>
    /// <param name="count">Number of random exams to generate (1 to 20, default 3).</param>
    /// <param name="modality">Optional modality code filter (e.g. CT, MR, US, DX, CR). If omitted, random modalities are picked.</param>
    /// <param name="date">Optional scheduled date in YYYYMMDD format. Defaults to today's date if omitted.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>HTTP 201 with summary and DICOM tag representations of created exams.</returns>
    [HttpPost("random")]
    [HttpGet("random")]
    [ProducesResponseType(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateRandomWorklist(
        [FromQuery] int count = 3,
        [FromQuery] string? modality = null,
        [FromQuery] string? date = null,
        CancellationToken cancellationToken = default)
    {
        // 1. Resolve Target Scheduled Date
        DateTime targetDate;
        if (!string.IsNullOrWhiteSpace(date))
        {
            var cleanDate = date.Trim();
            if (cleanDate.Contains('-'))
            {
                cleanDate = cleanDate.Split('-')[0].Trim();
            }

            if (!DateTime.TryParseExact(cleanDate, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out targetDate))
            {
                _logger.LogWarning("Invalid date parameter received for random generation: '{Date}'. Expected YYYYMMDD.", date);
                return BadRequest(new { error = $"Invalid date format '{date}'. Expected YYYYMMDD." });
            }
        }
        else
        {
            targetDate = DateTime.UtcNow.Date;
        }

        // Clamp count between 1 and 20
        var effectiveCount = Math.Clamp(count <= 0 ? 3 : count, 1, 20);
        _logger.LogInformation("Generating {Count} random MWL test exams. Modality='{Modality}', TargetDate='{Date}'",
            effectiveCount, modality ?? "ANY", targetDate.ToString("yyyy-MM-dd"));

        try
        {
            var createdPatients = new List<Patient>();
            var createdExams = new List<Exam>();

            // Determine candidate catalog entries based on optional modality
            var catalog = ProcedureCatalog;
            if (!string.IsNullOrWhiteSpace(modality))
            {
                var upperMod = modality.Trim().ToUpperInvariant();
                var filtered = ProcedureCatalog.Where(p => p.Modality == upperMod).ToArray();
                if (filtered.Length > 0)
                {
                    catalog = filtered;
                }
                else
                {
                    // Fallback catalog entry for custom modality
                    catalog = new[] { (upperMod, $"{upperMod} Examination", $"{upperMod}_SCANNER_01") };
                }
            }

            for (var i = 0; i < effectiveCount; i++)
            {
                // A. Random Patient Demographics
                var (firstName, sex) = FirstNames[Random.Shared.Next(FirstNames.Length)];
                var lastName = LastNames[Random.Shared.Next(LastNames.Length)];
                var birthYear = DateTime.UtcNow.Year - Random.Shared.Next(18, 80);
                var birthMonth = Random.Shared.Next(1, 13);
                var birthDay = Random.Shared.Next(1, 29);
                var birthDate = DateTime.SpecifyKind(new DateTime(birthYear, birthMonth, birthDay), DateTimeKind.Utc);

                var patSuffix = Random.Shared.Next(100, 999);
                var patCode = Guid.NewGuid().ToString("N")[..4].ToUpperInvariant();
                var patientId = $"PAT-{patSuffix}-{patCode}";
                var mrn = $"MRN-{DateTime.UtcNow:yyyy}-{Random.Shared.Next(1000, 9999)}";

                var patient = new Patient
                {
                    Id = Guid.NewGuid(),
                    PatientId = patientId,
                    Mrn = mrn,
                    FirstName = firstName,
                    LastName = lastName,
                    FullName = $"{firstName} {lastName}",
                    BirthDate = birthDate,
                    Sex = sex,
                    Gender = sex == "M" ? "Male" : "Female"
                };

                // B. Random Procedure Details
                var proc = catalog[Random.Shared.Next(catalog.Length)];
                var referring = ReferringPhysicians[Random.Shared.Next(ReferringPhysicians.Length)];
                var performing = PerformingPhysicians[Random.Shared.Next(PerformingPhysicians.Length)];

                // Scheduled Time today between 08:00 and 17:30
                var hour = Random.Shared.Next(8, 17);
                var minute = Random.Shared.Next(0, 4) * 15;
                var scheduledTime = DateTime.SpecifyKind(
                    targetDate.Date.AddHours(hour).AddMinutes(minute),
                    DateTimeKind.Utc);

                // Accession Number: exactly 15 chars (VR SH max 16 chars)
                var accSuffix = Random.Shared.Next(1000, 9999);
                var accessionNumber = $"ACC{targetDate:yyyyMMdd}{accSuffix}";

                var examId = Guid.NewGuid();
                var shortUid = examId.ToString("N")[..6].ToUpperInvariant();
                var exam = new Exam
                {
                    Id = examId,
                    AccessionNumber = accessionNumber,
                    Modality = proc.Modality,
                    ScheduledDateTime = scheduledTime,
                    StationAeTitle = proc.StationAe,
                    ProcedureDescription = proc.Description,
                    RequestedProcedureId = $"RP-{proc.Modality}-{shortUid[..4]}",
                    ScheduledProcedureStepId = $"SPS-{shortUid}",
                    ReferringPhysician = referring,
                    PerformingPhysician = performing,
                    StudyInstanceUid = GenerateStudyInstanceUid(examId),
                    Status = ExamStatus.Scheduled,
                    PatientId = patient.Id,
                    Patient = patient
                };

                patient.Exams.Add(exam);
                createdPatients.Add(patient);
                createdExams.Add(exam);
            }

            // Persist to PostgreSQL database
            await _dbContext.Patients.AddRangeAsync(createdPatients, cancellationToken);
            await _dbContext.Exams.AddRangeAsync(createdExams, cancellationToken);
            await _dbContext.SaveChangesAsync(cancellationToken);

            _logger.LogInformation("Successfully persisted {Count} random test exam(s) and patients.", createdExams.Count);

            // Build response payload with both structured details and DICOM tag mapping
            var responseExams = createdExams.Select(exam => new
            {
                id = exam.Id,
                accessionNumber = exam.AccessionNumber,
                modality = exam.Modality,
                scheduledDateTime = exam.ScheduledDateTime,
                procedureDescription = exam.ProcedureDescription,
                stationAeTitle = exam.StationAeTitle,
                studyInstanceUid = exam.StudyInstanceUid,
                status = exam.Status.ToString(),
                patient = new
                {
                    id = exam.Patient.Id,
                    patientId = exam.Patient.PatientId,
                    mrn = exam.Patient.Mrn,
                    firstName = exam.Patient.FirstName,
                    lastName = exam.Patient.LastName,
                    fullName = exam.Patient.FullName,
                    dicomPersonName = FormatDicomPersonName(exam.Patient.LastName, exam.Patient.FirstName, exam.Patient.FullName),
                    birthDate = exam.Patient.BirthDate?.ToString("yyyy-MM-dd"),
                    sex = exam.Patient.Sex
                },
                dicomWorklistTags = MapToDicomDataset(exam)
            }).ToList();

            return StatusCode(StatusCodes.Status201Created, new
            {
                message = $"Successfully generated and saved {createdExams.Count} random Modality Worklist example(s).",
                count = createdExams.Count,
                scheduledDate = targetDate.ToString("yyyy-MM-dd"),
                exams = responseExams
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to generate random worklist examples.");
            return StatusCode(500, new { error = "An internal server error occurred while generating random worklist items." });
        }
    }

    /// <summary>
    /// Maps an Exam entity and its associated Patient into a dictionary of explicit DICOM Hexadecimal tags.
    /// Follows DICOM PS 3.4 Annex K Modality Worklist standard.
    /// </summary>
    public static Dictionary<string, object?> MapToDicomDataset(Exam exam)
    {
        var patient = exam.Patient;

        // Patient Name in DICOM PN format: LastName^FirstName (or fallback to FullName)
        var formattedPatientName = FormatDicomPersonName(patient.LastName, patient.FirstName, patient.FullName);

        // Patient Birth Date in DICOM DA format: YYYYMMDD
        var formattedBirthDate = patient.BirthDate.HasValue
            ? patient.BirthDate.Value.ToString("yyyyMMdd", CultureInfo.InvariantCulture)
            : string.Empty;

        // Scheduled Step Date (YYYYMMDD) and Time (HHMMSS)
        var stepDate = exam.ScheduledDateTime.ToString("yyyyMMdd", CultureInfo.InvariantCulture);
        var stepTime = exam.ScheduledDateTime.ToString("HHmmss", CultureInfo.InvariantCulture);

        // Ensure Study Instance UID exists or generate a deterministic/standard UID
        var studyInstanceUid = !string.IsNullOrWhiteSpace(exam.StudyInstanceUid)
            ? exam.StudyInstanceUid
            : GenerateStudyInstanceUid(exam.Id);

        // Scheduled Procedure Step Sequence (0040,0100)
        var spsItem = new Dictionary<string, object?>
        {
            ["0040,0001"] = !string.IsNullOrWhiteSpace(exam.StationAeTitle) ? exam.StationAeTitle : "ORTHANC", // Scheduled Station AE Title
            ["0040,0002"] = stepDate,                                                                         // Scheduled Procedure Step Start Date
            ["0040,0003"] = stepTime,                                                                         // Scheduled Procedure Step Start Time
            ["0008,0060"] = exam.Modality?.ToUpperInvariant() ?? "OT",                                        // Modality
            ["0040,0007"] = exam.ProcedureDescription ?? "Diagnostic Imaging",                               // Scheduled Procedure Step Description
            ["0040,0009"] = !string.IsNullOrWhiteSpace(exam.ScheduledProcedureStepId)
                ? exam.ScheduledProcedureStepId
                : $"SPS-{exam.Id.ToString("N")[..8].ToUpperInvariant()}",                                     // Scheduled Procedure Step ID (max 16 chars)
            ["0040,0006"] = exam.PerformingPhysician ?? string.Empty                                          // Scheduled Performing Physician's Name
        };

        // Root DICOM Dataset Map
        return new Dictionary<string, object?>
        {
            // Patient Demographics & Identification
            ["0010,0010"] = formattedPatientName,                                                             // Patient's Name (LastName^FirstName)
            ["0010,0020"] = patient.PatientId ?? patient.Mrn ?? string.Empty,                                // Patient ID / MRN
            ["0010,0030"] = formattedBirthDate,                                                               // Patient's Birth Date (YYYYMMDD)
            ["0010,0040"] = FormatDicomSex(patient.Sex ?? patient.Gender),                                   // Patient's Sex (M, F, O)

            // Requested Procedure & Study Identification
            ["0008,0050"] = exam.AccessionNumber ?? string.Empty,                                             // Accession Number
            ["0020,000d"] = studyInstanceUid,                                                                 // Study Instance UID
            ["0008,0090"] = exam.ReferringPhysician ?? string.Empty,                                          // Referring Physician's Name
            ["0032,1060"] = exam.ProcedureDescription ?? string.Empty,                                       // Requested Procedure Description
            ["0040,1001"] = !string.IsNullOrWhiteSpace(exam.RequestedProcedureId)
                ? exam.RequestedProcedureId
                : $"RP-{exam.Id.ToString("N")[..8].ToUpperInvariant()}",                                      // Requested Procedure ID (max 16 chars)

            // Character Set & SOP Class UID
            ["0008,0005"] = "ISO_IR 100",                                                                     // Specific Character Set (Latin-1)
            ["0008,0016"] = "1.2.840.10008.5.1.4.31",                                                         // SOP Class UID (Modality Worklist FIND)

            // Scheduled Procedure Step Sequence (0040,0100) - Nested Array
            ["0040,0100"] = new List<Dictionary<string, object?>> { spsItem }
        };
    }

    /// <summary>
    /// Formats person name into DICOM Person Name (PN) format: LastName^FirstName.
    /// </summary>
    private static string FormatDicomPersonName(string? lastName, string? firstName, string? fullName)
    {
        if (!string.IsNullOrWhiteSpace(lastName) || !string.IsNullOrWhiteSpace(firstName))
        {
            return $"{(lastName ?? "").Trim()}^{(firstName ?? "").Trim()}".Trim('^');
        }

        if (!string.IsNullOrWhiteSpace(fullName))
        {
            var parts = fullName.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 1) return parts[0];
            // Format as Last^First
            return $"{parts[^1]}^{string.Join(" ", parts.Take(parts.Length - 1))}";
        }

        return "UNKNOWN^PATIENT";
    }

    /// <summary>
    /// Formats sex to standard DICOM CS value: M, F, or O.
    /// </summary>
    private static string FormatDicomSex(string? sex)
    {
        if (string.IsNullOrWhiteSpace(sex)) return "O";
        var s = sex.Trim().ToUpperInvariant();
        if (s.StartsWith("M")) return "M";
        if (s.StartsWith("F")) return "F";
        return "O";
    }

    /// <summary>
    /// Generates a standard DICOM UID if none exists.
    /// </summary>
    private static string GenerateStudyInstanceUid(Guid examId)
    {
        // 2.25 prefix followed by positive decimal integer representation of UUID
        var bytes = examId.ToByteArray();
        var bigInt = new System.Numerics.BigInteger(bytes, isUnsigned: true, isBigEndian: true);
        return $"2.25.{bigInt}";
    }

    #region Random Generation Reference Catalogs

    private static readonly (string Modality, string Description, string StationAe)[] ProcedureCatalog =
    {
        ("CT", "CT Chest with IV Contrast", "CT_SCANNER_01"),
        ("CT", "CT Abdomen & Pelvis with Contrast", "CT_SCANNER_02"),
        ("CT", "CT Head Non-Contrast", "CT_SCANNER_01"),
        ("CT", "CT Angiography Coronary", "CT_SCANNER_02"),
        ("CT", "CT Cervical Spine Non-Contrast", "CT_SCANNER_01"),
        ("MR", "MRI Brain with & without Contrast", "MR_SCANNER_3T"),
        ("MR", "MRI Lumbar Spine Without Contrast", "MR_SCANNER_15T"),
        ("MR", "MRI Left Knee Without Contrast", "MR_SCANNER_3T"),
        ("MR", "MRI Right Shoulder Arthrogram", "MR_SCANNER_3T"),
        ("MR", "MRI Cervical Spine", "MR_SCANNER_15T"),
        ("US", "Ultrasound Whole Abdomen", "US_ROOM_1"),
        ("US", "Ultrasound Thyroid", "US_ROOM_2"),
        ("US", "Ultrasound Carotid Doppler Bilateral", "US_ROOM_1"),
        ("US", "Ultrasound Pelvis Non-Obstetric", "US_ROOM_2"),
        ("DX", "Chest 2 Views PA and Lateral", "XRAY_ROOM_1"),
        ("DX", "Spine Lumbar 2 or 3 Views", "XRAY_ROOM_1"),
        ("DX", "Pelvis 1 or 2 Views", "XRAY_ROOM_2"),
        ("CR", "Chest Portable 1 View AP", "CR_PORTABLE_01"),
        ("CR", "Abdomen Portable 1 View", "CR_PORTABLE_01"),
        ("XA", "Coronary Angiogram Diagnostic", "CATH_LAB_1"),
        ("XA", "Left Heart Catheterization", "CATH_LAB_2")
    };

    private static readonly (string FirstName, string Sex)[] FirstNames =
    {
        ("James", "M"), ("John", "M"), ("Robert", "M"), ("Michael", "M"),
        ("William", "M"), ("David", "M"), ("Richard", "M"), ("Joseph", "M"),
        ("Thomas", "M"), ("Charles", "M"), ("Daniel", "M"), ("Matthew", "M"),
        ("Lucas", "M"), ("Alexander", "M"), ("Ethan", "M"), ("Oliver", "M"),
        ("Mary", "F"), ("Patricia", "F"), ("Jennifer", "F"), ("Linda", "F"),
        ("Elizabeth", "F"), ("Barbara", "F"), ("Susan", "F"), ("Jessica", "F"),
        ("Sarah", "F"), ("Karen", "F"), ("Sophia", "F"), ("Emma", "F"),
        ("Olivia", "F"), ("Ava", "F"), ("Isabella", "F"), ("Mia", "F")
    };

    private static readonly string[] LastNames =
    {
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
        "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
        "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
        "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris"
    };

    private static readonly string[] ReferringPhysicians =
    {
        "House^Gregory", "Wilson^James", "Cuddy^Lisa", "Foreman^Eric",
        "Cameron^Allison", "Chase^Robert", "Miller^Sarah", "Watson^John"
    };

    private static readonly string[] PerformingPhysicians =
    {
        "Taylor^Mark", "Grey^Meredith", "Shepherd^Derek", "Bailey^Miranda",
        "Cox^Perry", "Dorian^John", "Turk^Christopher", "Kovach^Luka"
    };

    #endregion
}
