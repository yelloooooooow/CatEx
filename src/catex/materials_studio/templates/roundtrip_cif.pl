use strict;
use warnings;
use MaterialsScript qw(:all);

die "Expected input CIF and two fixed output names" unless scalar(@ARGV) == 3;
my ($input_cif, $xsd_name, $cif_name) = @ARGV;
die "Unexpected XSD output name" unless $xsd_name eq "roundtrip.xsd";
die "Unexpected CIF output name" unless $cif_name eq "roundtrip.cif";

my $source = Documents->Import($input_cif);
my $xsd = Documents->New($xsd_name);
$xsd->CopyFrom($source);
$xsd->Export($cif_name);
