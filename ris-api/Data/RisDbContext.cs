using Microsoft.EntityFrameworkCore;
using RisApi.Models;

namespace RisApi.Data;

public class RisDbContext : DbContext
{
    public RisDbContext(DbContextOptions<RisDbContext> options) : base(options)
    {
    }

    public DbSet<Exam> Exams => Set<Exam>();
    public DbSet<Patient> Patients => Set<Patient>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<Exam>(entity =>
        {
            entity.HasIndex(e => e.AccessionNumber).IsUnique();
            entity.HasIndex(e => new { e.ScheduledDateTime, e.Modality });
            entity.HasOne(e => e.Patient)
                  .WithMany(p => p.Exams)
                  .HasForeignKey(e => e.PatientId)
                  .OnDelete(DeleteBehavior.Restrict);
        });

        modelBuilder.Entity<Patient>(entity =>
        {
            entity.HasIndex(p => p.PatientId).IsUnique();
        });
    }
}
