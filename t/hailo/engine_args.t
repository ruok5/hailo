use v5.10.0;
use strict;
use warnings;
use Test::More tests => 11;
use Hailo;

$SIG{__WARN__} = sub {
    print STDERR @_ if $_[0] !~ m/(?:^Issuing rollback|for database handle being DESTROY)/
};

# Default rareness flows through and matches historical default of 2.
{
    my $h = Hailo->new;
    $h->learn("hello there good sirs");
    is( $h->_engine->rareness, 2, "default rareness is 2" );
}

# Default repeat_limit flows through (min(order*10, 50); default order=5 => 50).
{
    my $h = Hailo->new;
    $h->learn("hello there good sirs");
    is( $h->_engine->repeat_limit, 20, "default repeat_limit is min(order*10, 50); default order=2 => 20" );
}

# engine_args rareness is applied to the constructed engine.
{
    my $h = Hailo->new( engine_args => { rareness => 1 } );
    $h->learn("hello there good sirs");
    is( $h->_engine->rareness, 1, "rareness=1 via engine_args" );
}

{
    my $h = Hailo->new( engine_args => { rareness => 7 } );
    $h->learn("hello there good sirs");
    is( $h->_engine->rareness, 7, "rareness=7 via engine_args" );
}

# engine_args repeat_limit is applied.
{
    my $h = Hailo->new( engine_args => { repeat_limit => 12 } );
    $h->learn("hello there good sirs");
    is( $h->_engine->repeat_limit, 12, "repeat_limit via engine_args" );
}

# Reply still works with a non-default rareness (smoke test against existing brain behavior).
{
    my $h = Hailo->new( engine_args => { rareness => 1 } );
    $h->learn("hello there good sirs");
    my $reply = $h->reply("hello");
    is( $reply, "Hello there good sirs.", "reply works with rareness=1" );
}

# Setting rareness very high on a tiny brain filters out every pivot candidate,
# so the engine falls back to a random expression but still returns a sentence.
# This guards against crashes when the knob is cranked.
{
    my $h = Hailo->new( engine_args => { rareness => 999 } );
    $h->learn("hello there good sirs");
    my $reply = $h->reply("hello");
    ok( defined $reply && length $reply, "reply defined even with rareness=999" );
}

# The Scored engine inherits rareness from Default and honors it when
# filtering input-token pivot candidates.
{
    my $h = Hailo->new(
        engine_class => 'Scored',
        engine_args  => { rareness => 1, iterations => 5 },
    );
    $h->learn("hello there good sirs");
    is( $h->_engine->rareness, 1, "Scored engine honors rareness arg" );
}

{
    my $h = Hailo->new(
        engine_class => 'Scored',
        engine_args  => { iterations => 5 },
    );
    $h->learn("hello there good sirs");
    is( $h->_engine->rareness, 2, "Scored engine inherits rareness default" );
}

# Smoke test: Scored produces a reply with rareness=1 on a tiny brain.
{
    my $h = Hailo->new(
        engine_class => 'Scored',
        engine_args  => { rareness => 1, iterations => 5 },
    );
    $h->learn("hello there good sirs");
    my $reply = $h->reply("hello");
    ok( defined $reply && length $reply, "Scored reply defined with rareness=1" );
}

# Smoke test: Scored still returns something when rareness filters every
# candidate (fallback to random expression via _generate_reply).
{
    my $h = Hailo->new(
        engine_class => 'Scored',
        engine_args  => { rareness => 999, iterations => 5 },
    );
    $h->learn("hello there good sirs");
    my $reply = $h->reply("hello");
    ok( defined $reply && length $reply, "Scored reply defined with rareness=999" );
}
