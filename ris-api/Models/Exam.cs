using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace RisApi.Models;

public enum ExamStatus
{
    Scheduled = 0,
    Waiting = 1,
    InRoom = 2,
    Completed = 3,
    Cancelled = 4
}

[Table("Exams")]
public class Exam
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    [MaxLength(64)]
    public string AccessionNumber { get; set; } = string.Empty;

    [Required]
    [MaxLength(16)]
    public string Modality { get; set; } = "CT";

    public DateTime ScheduledDateTime { get; set; }

    [MaxLength(64)]
    public string? StationAeTitle { get; set; }

    [MaxLength(256)]
    public string? ProcedureDescription { get; set; }

    [MaxLength(64)]
    public string? RequestedProcedureId { get; set; }

    [MaxLength(64)]
    public string? ScheduledProcedureStepId { get; set; }

    [MaxLength(128)]
    public string? ReferringPhysician { get; set; }

    [MaxLength(128)]
    public string? PerformingPhysician { get; set; }

    [MaxLength(128)]
    public string? StudyInstanceUid { get; set; }

    public ExamStatus Status { get; set; } = ExamStatus.Scheduled;

    public DateTime? CompletionDateTime { get; set; }

    // Relationship to Patient
    [Required]
    public Guid PatientId { get; set; }

    [ForeignKey(nameof(PatientId))]
    public Patient Patient { get; set; } = null!;
}
