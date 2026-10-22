using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace RisApi.Models;

[Table("Patients")]
public class Patient
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    [MaxLength(64)]
    public string PatientId { get; set; } = string.Empty; // MRN or Patient ID

    [MaxLength(64)]
    public string? Mrn { get; set; }

    [MaxLength(64)]
    public string? FirstName { get; set; }

    [MaxLength(64)]
    public string? LastName { get; set; }

    [MaxLength(128)]
    public string? FullName { get; set; }

    public DateTime? BirthDate { get; set; }

    [MaxLength(16)]
    public string? Sex { get; set; } // M, F, O

    [MaxLength(16)]
    public string? Gender { get; set; }

    // Navigation property
    public ICollection<Exam> Exams { get; set; } = new List<Exam>();
}
